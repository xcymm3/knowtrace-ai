from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import anyio
from arq import Retry

from app.core.config import Settings
from app.core.errors import ApiError
from app.features.documents.parser import limit_extracted_text, parse_document
from app.features.documents.store import create_supabase_client
from app.features.knowledge.chunker import chunk_text
from app.features.knowledge.embeddings import OpenAICompatibleEmbeddingProvider
from app.features.knowledge.store import SupabaseKnowledgeStore
from app.features.tasks.store import SupabaseTaskStore


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_error_message(error: Exception) -> str:
    return str(error).replace("\n", " ").strip()[:500] or "资料解析失败。"


async def _update_task(store: SupabaseTaskStore, task_id: UUID, data: dict[str, Any]) -> None:
    await anyio.to_thread.run_sync(store.update_task, task_id, data)


async def _is_task_cancelled(store: SupabaseTaskStore, task_id: UUID) -> bool:
    task = await anyio.to_thread.run_sync(store.get_task, task_id)
    return task["status"] == "CANCELLED"


async def process_parse_document(
    store: SupabaseTaskStore,
    task_id: UUID,
    attempt: int,
    max_extracted_characters: int,
    enqueue_embedding: Callable[[UUID], Awaitable[None]] | None = None,
) -> None:
    """Extract a document in the worker and persist a bounded text artifact.

    Parsing deliberately stops at PARSED. Step seven owns the separate chunk
    and embedding job, so a model outage never makes parsing appear failed.
    """
    task = await anyio.to_thread.run_sync(store.get_task, task_id)
    if task["status"] == "CANCELLED":
        return
    document_id = UUID(str(task["document_id"]))
    max_attempts = int(task["max_attempts"])

    await _update_task(
        store,
        task_id,
        {
            "status": "RUNNING",
            "progress": 10,
            "attempt_count": attempt,
            "started_at": _utc_now(),
            "completed_at": None,
        },
    )

    try:
        document = await anyio.to_thread.run_sync(store.get_document, document_id)
        await anyio.to_thread.run_sync(store.update_document, document_id, {"status": "PROCESSING"})
        await _update_task(store, task_id, {"progress": 30})

        content = await anyio.to_thread.run_sync(store.download_file, document["storage_path"])
        parsed = limit_extracted_text(
            parse_document(content, document["mime_type"], document["file_name"]),
            max_extracted_characters,
        )
        if await _is_task_cancelled(store, task_id):
            return
        await _update_task(store, task_id, {"progress": 70})

        metadata = dict(document.get("metadata") or {})
        metadata["parse"] = {
            **parsed.metadata,
            "needsOcr": parsed.needs_ocr,
            "hasExtractedText": bool(parsed.text),
        }
        index_task_id: UUID | None = None
        document_status = "PARSED"
        if parsed.text:
            derived_path = f"{document['workspace_id']}/{document_id}/derived/extracted.txt"
            await anyio.to_thread.run_sync(
                store.upload_derived_text, derived_path, parsed.text.encode("utf-8")
            )
            metadata["extractedTextPath"] = derived_path

            if enqueue_embedding and not await _is_task_cancelled(store, task_id):
                index_task_id = uuid4()
                await anyio.to_thread.run_sync(
                    store.create_embedding_task,
                    {
                        "id": str(index_task_id),
                        "workspace_id": document["workspace_id"],
                        "document_id": str(document_id),
                        "task_type": "GENERATE_EMBEDDINGS",
                        "status": "QUEUED",
                        "input_payload": {"sourceTaskId": str(task_id)},
                    },
                )
                metadata["index"] = {"status": "QUEUED", "taskId": str(index_task_id)}
                document_status = "PROCESSING"

        if await _is_task_cancelled(store, task_id):
            return
        await anyio.to_thread.run_sync(
            store.update_document,
            document_id,
            {"status": document_status, "metadata": metadata, "error_message": None},
        )
        if index_task_id:
            try:
                await enqueue_embedding(index_task_id)  # type: ignore[misc]
            except Exception as error:
                metadata["index"] = {
                    "status": "QUEUED",
                    "taskId": str(index_task_id),
                    "queueError": _safe_error_message(error),
                }
                await anyio.to_thread.run_sync(
                    store.update_document,
                    document_id,
                    {"status": "PARSED", "metadata": metadata},
                )
        await _update_task(
            store,
            task_id,
            {
                "status": "SUCCEEDED",
                "progress": 100,
                "output_payload": {
                    "parser": parsed.metadata.get("parser"),
                    "characterCount": len(parsed.text),
                    "needsOcr": parsed.needs_ocr,
                    "indexStatus": "QUEUED" if index_task_id else "PENDING",
                    "embeddingTaskId": str(index_task_id) if index_task_id else None,
                },
                "error_message": None,
                "completed_at": _utc_now(),
            },
        )
    except Exception as error:
        message = error.message if isinstance(error, ApiError) else _safe_error_message(error)
        retryable = not isinstance(error, ApiError) or error.status_code >= 500
        if retryable and attempt < max_attempts:
            await anyio.to_thread.run_sync(
                store.update_document,
                document_id,
                {"status": "PENDING", "error_message": message},
            )
            await _update_task(
                store,
                task_id,
                {
                    "status": "QUEUED",
                    "progress": 0,
                    "attempt_count": attempt,
                    "error_message": message,
                },
            )
            raise Retry(defer=attempt * 5) from error

        await anyio.to_thread.run_sync(
            store.update_document,
            document_id,
            {"status": "FAILED", "error_message": message},
        )
        await _update_task(
            store,
            task_id,
            {
                "status": "FAILED",
                "progress": 100,
                "attempt_count": attempt,
                "error_message": message,
                "completed_at": _utc_now(),
            },
        )
        raise


async def parse_document_task(ctx: dict[str, Any], task_id: str) -> None:
    """ARQ entry point for one queued document parser task."""
    settings = Settings()
    store = SupabaseTaskStore(
        create_supabase_client(settings),
        settings.supabase_storage_bucket,
    )

    async def enqueue_embedding(embedding_task_id: UUID) -> None:
        await ctx["redis"].enqueue_job(
            "generate_embeddings_task",
            str(embedding_task_id),
            _job_id=f"generate-embeddings:{embedding_task_id}",
            _queue_name="knowtrace:tasks",
        )

    await process_parse_document(
        store,
        UUID(task_id),
        int(ctx.get("job_try", 1)),
        settings.document_max_extracted_characters,
        enqueue_embedding,
    )


async def process_generate_embeddings(
    task_store: SupabaseTaskStore,
    knowledge_store: SupabaseKnowledgeStore,
    embeddings: OpenAICompatibleEmbeddingProvider,
    task_id: UUID,
    attempt: int,
    embedding_model: str,
) -> None:
    """Chunk one parsed document, embed its chunks, and atomically replace its index."""
    task = await anyio.to_thread.run_sync(task_store.get_task, task_id)
    if task["status"] == "CANCELLED":
        return
    document_id = UUID(str(task["document_id"]))
    max_attempts = int(task["max_attempts"])
    document: dict[str, Any] | None = None

    await _update_task(
        task_store,
        task_id,
        {
            "status": "RUNNING",
            "progress": 10,
            "attempt_count": attempt,
            "started_at": _utc_now(),
            "completed_at": None,
        },
    )

    try:
        document = await anyio.to_thread.run_sync(knowledge_store.get_document, document_id)
        metadata = dict(document.get("metadata") or {})
        extracted_path = metadata.get("extractedTextPath")
        if not isinstance(extracted_path, str) or not extracted_path:
            raise ApiError(422, "DOCUMENT_TEXT_UNAVAILABLE", "资料没有可供检索的文本内容。")

        extracted = await anyio.to_thread.run_sync(
            knowledge_store.download_file, document["storage_bucket"], extracted_path
        )
        chunks = chunk_text(extracted.decode("utf-8"))
        if not chunks:
            raise ApiError(422, "DOCUMENT_TEXT_UNAVAILABLE", "资料没有可供检索的文本内容。")
        await _update_task(task_store, task_id, {"progress": 30})

        vectors: list[list[float]] = []
        batch_size = 32
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors.extend(await embeddings.embed([chunk.content for chunk in batch]))
            progress = 30 + int(50 * min(start + len(batch), len(chunks)) / len(chunks))
            await _update_task(task_store, task_id, {"progress": progress})

        if await _is_task_cancelled(task_store, task_id):
            return

        records = [
            {
                "workspace_id": document["workspace_id"],
                "document_id": str(document_id),
                "chunk_index": chunk.index,
                "content": chunk.content,
                "token_count": max(1, len(chunk.content.split())),
                "embedding": vector,
                "metadata": {**chunk.metadata, "chunkIndex": chunk.index},
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        if await _is_task_cancelled(task_store, task_id):
            return
        await anyio.to_thread.run_sync(knowledge_store.replace_chunks, document_id, records)
        metadata["index"] = {
            "status": "READY",
            "chunkCount": len(records),
            "embeddingModel": embedding_model,
            "updatedAt": _utc_now(),
        }
        await anyio.to_thread.run_sync(
            task_store.update_document,
            document_id,
            {"status": "READY", "metadata": metadata, "error_message": None},
        )
        await _update_task(
            task_store,
            task_id,
            {
                "status": "SUCCEEDED",
                "progress": 100,
                "output_payload": {"chunkCount": len(records), "embeddingModel": embedding_model},
                "error_message": None,
                "completed_at": _utc_now(),
            },
        )
    except Exception as error:
        message = error.message if isinstance(error, ApiError) else _safe_error_message(error)
        retryable = not isinstance(error, ApiError) or error.status_code >= 500
        if retryable and attempt < max_attempts:
            if document:
                metadata = dict(document.get("metadata") or {})
                metadata["index"] = {"status": "QUEUED", "lastError": message}
                await anyio.to_thread.run_sync(
                    task_store.update_document,
                    document_id,
                    {"status": "PARSED", "metadata": metadata, "error_message": message},
                )
            await _update_task(
                task_store,
                task_id,
                {
                    "status": "QUEUED",
                    "progress": 0,
                    "attempt_count": attempt,
                    "error_message": message,
                },
            )
            raise Retry(defer=attempt * 5) from error

        if document:
            metadata = dict(document.get("metadata") or {})
            metadata["index"] = {"status": "FAILED", "lastError": message}
            await anyio.to_thread.run_sync(
                task_store.update_document,
                document_id,
                {"status": "FAILED", "metadata": metadata, "error_message": message},
            )
        await _update_task(
            task_store,
            task_id,
            {
                "status": "FAILED",
                "progress": 100,
                "attempt_count": attempt,
                "error_message": message,
                "completed_at": _utc_now(),
            },
        )
        raise


async def generate_embeddings_task(ctx: dict[str, Any], task_id: str) -> None:
    """ARQ entry point for one queued chunk-and-embedding task."""
    settings = Settings()
    client = create_supabase_client(settings)
    await process_generate_embeddings(
        SupabaseTaskStore(client, settings.supabase_storage_bucket),
        SupabaseKnowledgeStore(client),
        OpenAICompatibleEmbeddingProvider(settings),
        UUID(task_id),
        int(ctx.get("job_try", 1)),
        settings.embedding_model,
    )

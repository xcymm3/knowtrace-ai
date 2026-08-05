from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import anyio
from arq import Retry

from app.core.config import Settings
from app.core.errors import ApiError
from app.features.documents.parser import parse_document
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


async def parse_document_task(ctx: dict[str, Any], task_id: str) -> None:
    """Consume a queued parse job and persist a Storage-backed extraction artifact."""
    settings = Settings()
    client = create_supabase_client(settings)
    store = SupabaseTaskStore(client, settings.supabase_storage_bucket)
    typed_task_id = UUID(task_id)
    task = await anyio.to_thread.run_sync(store.get_task, typed_task_id)
    document_id = UUID(task["document_id"])
    attempt = int(ctx.get("job_try", 1))

    if task["status"] == "CANCELLED":
        return

    await _update_task(
        store,
        typed_task_id,
        {"status": "RUNNING", "progress": 10, "attempt_count": attempt, "started_at": _utc_now()},
    )

    try:
        document = await anyio.to_thread.run_sync(store.get_document, document_id)
        await anyio.to_thread.run_sync(store.update_document, document_id, {"status": "PROCESSING"})
        await _update_task(store, typed_task_id, {"progress": 30})

        content = await anyio.to_thread.run_sync(store.download_file, document["storage_path"])
        parsed = parse_document(content, document["mime_type"], document["file_name"])
        await _update_task(store, typed_task_id, {"progress": 70})

        metadata = dict(document.get("metadata") or {})
        metadata["parse"] = {**parsed.metadata, "needsOcr": parsed.needs_ocr}

        if parsed.text:
            derived_path = f"{document['project_id']}/{document_id}/derived/extracted.txt"
            await anyio.to_thread.run_sync(
                store.upload_derived_text, derived_path, parsed.text.encode("utf-8")
            )
            metadata["extractedTextPath"] = derived_path

        await anyio.to_thread.run_sync(
            store.update_document,
            document_id,
            {"status": "READY", "metadata": metadata, "error_message": None},
        )
        output_payload: dict[str, Any] = {
            "parser": parsed.metadata.get("parser"),
            "characterCount": len(parsed.text),
            "needsOcr": parsed.needs_ocr,
        }
        if parsed.text:
            embedding_task = await anyio.to_thread.run_sync(
                store.create_embedding_task,
                {
                    "id": str(uuid4()),
                    "project_id": document["project_id"],
                    "document_id": str(document_id),
                    "task_type": "GENERATE_EMBEDDINGS",
                    "status": "QUEUED",
                    "input_payload": {"sourceTaskId": str(typed_task_id)},
                },
            )
            embedding_task_id = UUID(embedding_task["id"])
            await ctx["redis"].enqueue_job(
                "generate_embeddings_task",
                str(embedding_task_id),
                _job_id=f"generate-embeddings:{embedding_task_id}",
                _queue_name="commercelens:tasks",
            )
            output_payload["embeddingTaskId"] = str(embedding_task_id)

        await _update_task(
            store,
            typed_task_id,
            {
                "status": "SUCCEEDED",
                "progress": 100,
                "output_payload": output_payload,
                "error_message": None,
                "completed_at": _utc_now(),
            },
        )
    except ApiError as error:
        await anyio.to_thread.run_sync(
            store.update_document,
            document_id,
            {"status": "FAILED", "error_message": error.message},
        )
        await _update_task(
            store,
            typed_task_id,
            {
                "status": "FAILED",
                "progress": 100,
                "error_message": error.message,
                "completed_at": _utc_now(),
            },
        )
        raise
    except Exception as error:
        message = _safe_error_message(error)
        max_attempts = int(task["max_attempts"])

        if attempt < max_attempts:
            await _update_task(
                store,
                typed_task_id,
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
            typed_task_id,
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
    """Chunk an extracted document, generate vectors, and atomically replace its index."""
    settings = Settings()
    client = create_supabase_client(settings)
    task_store = SupabaseTaskStore(client, settings.supabase_storage_bucket)
    knowledge_store = SupabaseKnowledgeStore(client)
    typed_task_id = UUID(task_id)
    task = await anyio.to_thread.run_sync(task_store.get_task, typed_task_id)
    document_id = UUID(task["document_id"])
    attempt = int(ctx.get("job_try", 1))

    if task["status"] == "CANCELLED":
        return

    await _update_task(
        task_store,
        typed_task_id,
        {"status": "RUNNING", "progress": 10, "attempt_count": attempt, "started_at": _utc_now()},
    )

    try:
        embeddings = OpenAICompatibleEmbeddingProvider(settings)
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
        await _update_task(task_store, typed_task_id, {"progress": 30})

        vectors: list[list[float]] = []
        batch_size = 32
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors.extend(await embeddings.embed([chunk.content for chunk in batch]))
            progress = 30 + int(50 * min(start + len(batch), len(chunks)) / len(chunks))
            await _update_task(task_store, typed_task_id, {"progress": progress})

        records = [
            {
                "document_id": str(document_id),
                "chunk_index": chunk.index,
                "content": chunk.content,
                "token_count": max(1, len(chunk.content.split())),
                "embedding": vector,
                "metadata": {**chunk.metadata, "chunkIndex": chunk.index},
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        await anyio.to_thread.run_sync(knowledge_store.replace_chunks, document_id, records)
        metadata["index"] = {
            "chunkCount": len(records),
            "embeddingModel": settings.embedding_model,
            "updatedAt": _utc_now(),
        }
        await anyio.to_thread.run_sync(
            task_store.update_document, document_id, {"metadata": metadata, "error_message": None}
        )
        await _update_task(
            task_store,
            typed_task_id,
            {
                "status": "SUCCEEDED",
                "progress": 100,
                "output_payload": {
                    "chunkCount": len(records),
                    "embeddingModel": settings.embedding_model,
                },
                "error_message": None,
                "completed_at": _utc_now(),
            },
        )
    except ApiError as error:
        await _update_task(
            task_store,
            typed_task_id,
            {
                "status": "FAILED",
                "progress": 100,
                "error_message": error.message,
                "completed_at": _utc_now(),
            },
        )
        raise
    except Exception as error:
        message = _safe_error_message(error)
        max_attempts = int(task["max_attempts"])
        if attempt < max_attempts:
            await _update_task(
                task_store,
                typed_task_id,
                {
                    "status": "QUEUED",
                    "progress": 0,
                    "attempt_count": attempt,
                    "error_message": message,
                },
            )
            raise Retry(defer=attempt * 5) from error
        await _update_task(
            task_store,
            typed_task_id,
            {
                "status": "FAILED",
                "progress": 100,
                "attempt_count": attempt,
                "error_message": message,
                "completed_at": _utc_now(),
            },
        )
        raise

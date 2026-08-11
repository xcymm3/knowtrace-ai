from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

import anyio

from app.core.errors import ApiError
from app.features.tasks.store import SupabaseTaskStore


class TaskQueue(Protocol):
    async def enqueue_parse_document(self, task_id: UUID) -> None: ...

    async def enqueue_generate_embeddings(self, task_id: UUID) -> None: ...


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class TaskControlService:
    """User-facing recovery controls around durable ingestion task records."""

    store: SupabaseTaskStore
    queue: TaskQueue

    async def retry_task(self, workspace_id: UUID, task_id: UUID) -> dict[str, Any]:
        task = await anyio.to_thread.run_sync(self.store.get_task, task_id)
        self._ensure_workspace(task, workspace_id)
        if task["status"] not in {"FAILED", "CANCELLED"}:
            raise ApiError(409, "TASK_NOT_RETRYABLE", "只有失败或已取消的任务可以重新尝试。")
        if not task.get("document_id"):
            raise ApiError(422, "TASK_DOCUMENT_REQUIRED", "该任务没有可重新处理的资料。")

        document_id = UUID(str(task["document_id"]))
        document = await anyio.to_thread.run_sync(self.store.get_document, document_id)
        self._ensure_workspace(document, workspace_id)

        retry_id = uuid4()
        task_type = str(task["task_type"])
        metadata = dict(document.get("metadata") or {})
        if task_type == "PARSE_DOCUMENT":
            document_status = "PENDING"
        elif task_type == "GENERATE_EMBEDDINGS":
            extracted_path = metadata.get("extractedTextPath")
            if not isinstance(extracted_path, str) or not extracted_path:
                raise ApiError(
                    422, "DOCUMENT_TEXT_UNAVAILABLE", "资料尚未完成文本解析，无法重新建立索引。"
                )
            document_status = "PROCESSING"
            metadata["index"] = {
                "status": "QUEUED",
                "taskId": str(retry_id),
                "retryOf": str(task_id),
            }
        else:
            raise ApiError(422, "TASK_TYPE_UNSUPPORTED", "当前任务类型暂不支持重新尝试。")

        await anyio.to_thread.run_sync(
            self.store.update_document,
            document_id,
            {"status": document_status, "metadata": metadata, "error_message": None},
        )
        retry_task = await anyio.to_thread.run_sync(
            self.store.create_task,
            {
                "id": str(retry_id),
                "workspace_id": str(workspace_id),
                "document_id": str(document_id),
                "task_type": task_type,
                "status": "QUEUED",
                "input_payload": {"documentId": str(document_id), "retryOf": str(task_id)},
            },
        )
        try:
            if task_type == "PARSE_DOCUMENT":
                await self.queue.enqueue_parse_document(retry_id)
            else:
                await self.queue.enqueue_generate_embeddings(retry_id)
        except Exception:
            # The durable QUEUED record is intentionally retained. A worker or
            # later workspace load can resume it when the queue is available.
            pass
        return retry_task

    async def cancel_task(self, workspace_id: UUID, task_id: UUID) -> dict[str, Any]:
        task = await anyio.to_thread.run_sync(self.store.get_task, task_id)
        self._ensure_workspace(task, workspace_id)
        if task["status"] not in {"QUEUED", "RUNNING"}:
            raise ApiError(409, "TASK_NOT_CANCELLABLE", "只有排队中或运行中的任务可以取消。")

        document_id = task.get("document_id")
        await anyio.to_thread.run_sync(
            self.store.update_task,
            task_id,
            {
                "status": "CANCELLED",
                "error_message": "已由用户取消。",
                "completed_at": _utc_now(),
            },
        )
        if document_id:
            document_uuid = UUID(str(document_id))
            document = await anyio.to_thread.run_sync(self.store.get_document, document_uuid)
            self._ensure_workspace(document, workspace_id)
            metadata = document.get("metadata") or {}
            has_extracted_text = isinstance(metadata.get("extractedTextPath"), str)
            await anyio.to_thread.run_sync(
                self.store.update_document,
                document_uuid,
                {
                    "status": "PARSED" if has_extracted_text else "PENDING",
                    "error_message": "处理已取消，可重新尝试。",
                },
            )
        return await anyio.to_thread.run_sync(self.store.get_task, task_id)

    async def delete_document(self, workspace_id: UUID, document_id: UUID) -> None:
        document = await anyio.to_thread.run_sync(self.store.get_document, document_id)
        self._ensure_workspace(document, workspace_id)
        metadata = dict(document.get("metadata") or {})
        paths = [str(document["storage_path"])]
        extracted_path = metadata.get("extractedTextPath")
        if isinstance(extracted_path, str):
            paths.append(extracted_path)
        await anyio.to_thread.run_sync(
            self.store.delete_storage_files,
            str(document.get("storage_bucket") or ""),
            paths,
        )
        await anyio.to_thread.run_sync(self.store.delete_document_records, document_id)

    @staticmethod
    def _ensure_workspace(record: dict[str, Any], workspace_id: UUID) -> None:
        if str(record.get("workspace_id")) != str(workspace_id):
            raise ApiError(404, "RESOURCE_NOT_FOUND", "未找到对应的知识库资料。")

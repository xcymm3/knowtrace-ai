from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Protocol
from uuid import UUID, uuid4

import anyio

from app.core.config import Settings
from app.core.errors import ApiError
from app.features.documents.parser import validate_document_type
from app.features.documents.schemas import DocumentKind, DocumentUploadResponse
from app.features.documents.store import DocumentStore


class ParseTaskQueue(Protocol):
    async def enqueue_parse_document(self, task_id: UUID) -> None: ...


@dataclass(frozen=True)
class UploadInput:
    project_id: UUID
    product_id: UUID | None
    kind: DocumentKind
    file_name: str
    mime_type: str
    content: bytes


class DocumentIngestionService:
    def __init__(self, store: DocumentStore, queue: ParseTaskQueue, settings: Settings) -> None:
        self._store = store
        self._queue = queue
        self._settings = settings

    @staticmethod
    def _sanitize_file_name(file_name: str) -> str:
        raw_name = PurePath(file_name).name or "uploaded-file"
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_name).strip(".-")
        return safe_name[:180] or "uploaded-file"

    async def list_documents(self, project_id: UUID) -> list[dict[str, object]]:
        exists = await anyio.to_thread.run_sync(self._store.project_exists, project_id)
        if not exists:
            raise ApiError(404, "PROJECT_NOT_FOUND", "未找到对应的调研项目。")
        return await anyio.to_thread.run_sync(self._store.list_project_documents, project_id)

    async def ingest(self, upload: UploadInput) -> DocumentUploadResponse:
        validate_document_type(upload.mime_type, upload.file_name)
        if len(upload.content) == 0:
            raise ApiError(422, "DOCUMENT_EMPTY", "上传文件不能为空。")
        if len(upload.content) > self._settings.document_max_upload_size_bytes:
            raise ApiError(413, "DOCUMENT_TOO_LARGE", "上传文件超过允许的大小。")

        project_exists = await anyio.to_thread.run_sync(
            self._store.project_exists, upload.project_id
        )
        if not project_exists:
            raise ApiError(404, "PROJECT_NOT_FOUND", "未找到对应的调研项目。")

        document_id = uuid4()
        task_id = uuid4()
        safe_file_name = self._sanitize_file_name(upload.file_name)
        storage_path = f"{upload.project_id}/{document_id}/original/{safe_file_name}"
        checksum = hashlib.sha256(upload.content).hexdigest()

        await anyio.to_thread.run_sync(
            self._store.upload_file,
            storage_path,
            upload.content,
            upload.mime_type,
        )

        document_data = {
            "id": str(document_id),
            "project_id": str(upload.project_id),
            "product_id": str(upload.product_id) if upload.product_id else None,
            "kind": upload.kind.value,
            "file_name": safe_file_name,
            "mime_type": upload.mime_type,
            "size_bytes": len(upload.content),
            "storage_bucket": self._settings.supabase_storage_bucket,
            "storage_path": storage_path,
            "checksum": checksum,
            "status": "PENDING",
            "metadata": {"ingestion": "api-upload"},
        }

        try:
            await anyio.to_thread.run_sync(self._store.create_source_document, document_data)
            task_data = {
                "id": str(task_id),
                "project_id": str(upload.project_id),
                "document_id": str(document_id),
                "task_type": "PARSE_DOCUMENT",
                "status": "QUEUED",
                "input_payload": {"documentId": str(document_id)},
            }
            await anyio.to_thread.run_sync(self._store.create_parse_task, task_data)
            await self._queue.enqueue_parse_document(task_id)
        except Exception:
            raise

        return DocumentUploadResponse(
            id=document_id,
            project_id=upload.project_id,
            product_id=upload.product_id,
            kind=upload.kind,
            file_name=document_data["file_name"],
            status="PENDING",
            task_id=task_id,
            task_status="QUEUED",
        )

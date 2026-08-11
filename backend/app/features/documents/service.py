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
from app.features.documents.parser import normalize_document_mime_type, validate_document_type
from app.features.documents.schemas import DocumentKind, DocumentUploadResponse
from app.features.documents.store import DocumentStore


class ParseTaskQueue(Protocol):
    async def enqueue_parse_document(self, task_id: UUID) -> None: ...


@dataclass(frozen=True)
class UploadInput:
    workspace_id: UUID
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
        safe_name = re.sub(r"[^\w.-]+", "-", raw_name, flags=re.UNICODE).strip(".-")
        return safe_name[:180] or "uploaded-file"

    async def list_documents(self, workspace_id: UUID) -> list[dict[str, object]]:
        exists = await anyio.to_thread.run_sync(self._store.workspace_exists, workspace_id)
        if not exists:
            raise ApiError(404, "WORKSPACE_NOT_FOUND", "未找到对应的工作区。")
        return await anyio.to_thread.run_sync(self._store.list_workspace_documents, workspace_id)

    async def ingest(self, upload: UploadInput) -> DocumentUploadResponse:
        mime_type = normalize_document_mime_type(upload.mime_type, upload.file_name)
        validate_document_type(mime_type, upload.file_name)
        if len(upload.content) == 0:
            raise ApiError(422, "DOCUMENT_EMPTY", "上传文件不能为空。")
        if len(upload.content) > self._settings.document_max_upload_size_bytes:
            raise ApiError(413, "DOCUMENT_TOO_LARGE", "上传文件超过允许的大小。")

        workspace_exists = await anyio.to_thread.run_sync(
            self._store.workspace_exists, upload.workspace_id
        )
        if not workspace_exists:
            raise ApiError(404, "WORKSPACE_NOT_FOUND", "未找到对应的工作区。")

        document_id = uuid4()
        task_id = uuid4()
        safe_file_name = self._sanitize_file_name(upload.file_name)
        storage_path = f"{upload.workspace_id}/{document_id}/original/{safe_file_name}"
        checksum = hashlib.sha256(upload.content).hexdigest()

        document_data = {
            "id": str(document_id),
            "workspace_id": str(upload.workspace_id),
            "kind": upload.kind.value,
            "file_name": safe_file_name,
            "mime_type": mime_type,
            "size_bytes": len(upload.content),
            "storage_bucket": self._settings.supabase_storage_bucket,
            "storage_path": storage_path,
            "checksum": checksum,
            "status": "PENDING",
            "metadata": {"ingestion": "api-upload", "checksumAlgorithm": "sha256"},
        }

        file_uploaded = False
        document_created = False
        try:
            await anyio.to_thread.run_sync(
                self._store.upload_file,
                storage_path,
                upload.content,
                mime_type,
            )
            file_uploaded = True
            await anyio.to_thread.run_sync(self._store.create_source_document, document_data)
            document_created = True
            task_data = {
                "id": str(task_id),
                "workspace_id": str(upload.workspace_id),
                "document_id": str(document_id),
                "task_type": "PARSE_DOCUMENT",
                "status": "QUEUED",
                "input_payload": {"documentId": str(document_id)},
            }
            await anyio.to_thread.run_sync(self._store.create_parse_task, task_data)
        except Exception:
            if document_created:
                await anyio.to_thread.run_sync(self._store.delete_source_document, document_id)
            if file_uploaded:
                await anyio.to_thread.run_sync(self._store.delete_file, storage_path)
            raise

        # The task is already durable at this point. If Redis is temporarily
        # unavailable, retaining a QUEUED task is safer than rolling back the
        # user's uploaded file; a restarted worker can process it later.
        try:
            await self._queue.enqueue_parse_document(task_id)
        except Exception:
            pass

        return DocumentUploadResponse(
            id=document_id,
            workspace_id=upload.workspace_id,
            kind=upload.kind,
            file_name=document_data["file_name"],
            status="PENDING",
            task_id=task_id,
            task_status="QUEUED",
        )

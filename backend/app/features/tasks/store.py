from __future__ import annotations

from typing import Any
from uuid import UUID

from supabase import Client

from app.core.errors import ApiError


class SupabaseTaskStore:
    def __init__(self, client: Client, storage_bucket: str) -> None:
        self._client = client
        self._storage_bucket = storage_bucket

    def get_task(self, task_id: UUID) -> dict[str, Any]:
        response = (
            self._client.table("processing_tasks").select("*").eq("id", str(task_id)).execute()
        )
        if not response.data:
            raise ApiError(404, "TASK_NOT_FOUND", "未找到对应的后台任务。")
        return response.data[0]

    def list_workspace_tasks(self, workspace_id: UUID) -> list[dict[str, Any]]:
        response = (
            self._client.table("processing_tasks")
            .select(
                "id,workspace_id,document_id,task_type,status,progress,attempt_count,max_attempts,"
                "output_payload,error_message,started_at,completed_at"
            )
            .eq("workspace_id", str(workspace_id))
            .order("created_at", desc=True)
            .execute()
        )
        return response.data or []

    def get_document(self, document_id: UUID) -> dict[str, Any]:
        response = (
            self._client.table("workspace_documents")
            .select("*")
            .eq("id", str(document_id))
            .execute()
        )
        if not response.data:
            raise ApiError(404, "DOCUMENT_NOT_FOUND", "未找到对应的调研资料。")
        return response.data[0]

    def update_task(self, task_id: UUID, data: dict[str, Any]) -> None:
        self._client.table("processing_tasks").update(data).eq("id", str(task_id)).execute()

    def update_document(self, document_id: UUID, data: dict[str, Any]) -> None:
        self._client.table("workspace_documents").update(data).eq("id", str(document_id)).execute()

    def create_embedding_task(self, data: dict[str, Any]) -> dict[str, Any]:
        response = self._client.table("processing_tasks").insert(data).execute()
        if not response.data:
            raise ApiError(502, "TASK_CREATE_FAILED", "Embedding 任务创建失败。")
        return response.data[0]

    def download_file(self, path: str) -> bytes:
        return self._client.storage.from_(self._storage_bucket).download(path)

    def upload_derived_text(self, path: str, content: bytes) -> None:
        self._client.storage.from_(self._storage_bucket).upload(
            path,
            content,
            file_options={"content-type": "text/plain; charset=utf-8", "upsert": "true"},
        )

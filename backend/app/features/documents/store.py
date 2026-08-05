from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from supabase import Client, create_client

from app.core.config import Settings
from app.core.errors import ApiError


class DocumentStore(Protocol):
    def project_exists(self, project_id: UUID) -> bool: ...

    def upload_file(self, path: str, content: bytes, mime_type: str) -> None: ...

    def create_source_document(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def create_parse_task(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def delete_file(self, path: str) -> None: ...


def create_supabase_client(settings: Settings) -> Client:
    if not settings.supabase_is_configured:
        raise ApiError(503, "SUPABASE_NOT_CONFIGURED", "Supabase 尚未完成配置。")

    return create_client(settings.supabase_url or "", settings.supabase_service_role_key or "")


class SupabaseDocumentStore:
    def __init__(self, client: Client, storage_bucket: str) -> None:
        self._client = client
        self._storage_bucket = storage_bucket

    def project_exists(self, project_id: UUID) -> bool:
        response = (
            self._client.table("research_projects").select("id").eq("id", str(project_id)).execute()
        )
        return bool(response.data)

    def upload_file(self, path: str, content: bytes, mime_type: str) -> None:
        self._client.storage.from_(self._storage_bucket).upload(
            path,
            content,
            file_options={"content-type": mime_type, "upsert": "false"},
        )

    def create_source_document(self, data: dict[str, Any]) -> dict[str, Any]:
        response = self._client.table("source_documents").insert(data).execute()
        if not response.data:
            raise ApiError(502, "DOCUMENT_CREATE_FAILED", "资料记录创建失败。")
        return response.data[0]

    def create_parse_task(self, data: dict[str, Any]) -> dict[str, Any]:
        response = self._client.table("research_tasks").insert(data).execute()
        if not response.data:
            raise ApiError(502, "TASK_CREATE_FAILED", "资料解析任务创建失败。")
        return response.data[0]

    def delete_file(self, path: str) -> None:
        self._client.storage.from_(self._storage_bucket).remove([path])

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from supabase import Client, create_client

from app.core.config import Settings
from app.core.errors import ApiError


class DocumentStore(Protocol):
    def workspace_exists(self, workspace_id: UUID) -> bool: ...

    def list_workspace_documents(self, workspace_id: UUID) -> list[dict[str, Any]]: ...

    def upload_file(self, path: str, content: bytes, mime_type: str) -> None: ...

    def create_source_document(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def delete_source_document(self, document_id: UUID) -> None: ...

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

    def workspace_exists(self, workspace_id: UUID) -> bool:
        response = (
            self._client.table("workspaces").select("id").eq("id", str(workspace_id)).execute()
        )
        return bool(response.data)

    def list_workspace_documents(self, workspace_id: UUID) -> list[dict[str, Any]]:
        response = (
            self._client.table("workspace_documents")
            .select(
                "id,workspace_id,kind,file_name,mime_type,size_bytes,status,"
                "error_message,metadata,created_at,updated_at"
            )
            .eq("workspace_id", str(workspace_id))
            .order("created_at", desc=True)
            .execute()
        )
        return response.data or []

    def upload_file(self, path: str, content: bytes, mime_type: str) -> None:
        try:
            self._client.storage.from_(self._storage_bucket).upload(
                path,
                content,
                file_options={"content-type": mime_type, "upsert": "false"},
            )
        except Exception as error:
            raise ApiError(
                502,
                "DOCUMENT_STORAGE_UPLOAD_FAILED",
                "文件未能保存到资料存储。请确认 Supabase 已执行最新 Storage Migration。",
            ) from error

    def create_source_document(self, data: dict[str, Any]) -> dict[str, Any]:
        response = self._client.table("workspace_documents").insert(data).execute()
        if not response.data:
            raise ApiError(502, "DOCUMENT_CREATE_FAILED", "知识资料记录创建失败。")
        return response.data[0]

    def delete_source_document(self, document_id: UUID) -> None:
        self._client.table("workspace_documents").delete().eq("id", str(document_id)).execute()

    def create_parse_task(self, data: dict[str, Any]) -> dict[str, Any]:
        response = self._client.table("processing_tasks").insert(data).execute()
        if not response.data:
            raise ApiError(502, "TASK_CREATE_FAILED", "资料解析任务创建失败。")
        return response.data[0]

    def delete_file(self, path: str) -> None:
        self._client.storage.from_(self._storage_bucket).remove([path])

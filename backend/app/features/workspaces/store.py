from __future__ import annotations

from typing import Any
from uuid import UUID

from supabase import Client

from app.core.errors import ApiError


class SupabaseWorkspaceStore:
    def __init__(self, client: Client) -> None:
        self._client = client

    def create_workspace(self, data: dict[str, Any]) -> dict[str, Any]:
        response = self._client.table("workspaces").insert(data).execute()
        if not response.data:
            raise ApiError(502, "WORKSPACE_CREATE_FAILED", "工作区创建失败。")
        return response.data[0]

    def list_workspaces(self, owner_id: UUID) -> list[dict[str, Any]]:
        response = (
            self._client.table("workspaces")
            .select("*")
            .eq("owner_id", str(owner_id))
            .order("updated_at", desc=True)
            .execute()
        )
        return response.data or []

    def get_workspace(self, workspace_id: UUID, owner_id: UUID) -> dict[str, Any]:
        response = (
            self._client.table("workspaces")
            .select("*")
            .eq("id", str(workspace_id))
            .eq("owner_id", str(owner_id))
            .execute()
        )
        if not response.data:
            raise ApiError(404, "WORKSPACE_NOT_FOUND", "未找到对应的工作区。")
        return response.data[0]

    def update_workspace(
        self, workspace_id: UUID, owner_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        response = (
            self._client.table("workspaces")
            .update(data)
            .eq("id", str(workspace_id))
            .eq("owner_id", str(owner_id))
            .execute()
        )
        if not response.data:
            raise ApiError(404, "WORKSPACE_NOT_FOUND", "未找到对应的工作区。")
        return response.data[0]

    def delete_workspace(self, workspace_id: UUID, owner_id: UUID) -> None:
        self.get_workspace(workspace_id, owner_id)
        documents = (
            self._client.table("workspace_documents")
            .select("storage_bucket,storage_path,metadata")
            .eq("workspace_id", str(workspace_id))
            .execute()
        ).data or []

        conversations = (
            self._client.table("conversations")
            .select("id")
            .eq("workspace_id", str(workspace_id))
            .execute()
        ).data or []
        conversation_ids = [str(conversation["id"]) for conversation in conversations]
        if conversation_ids:
            messages = (
                self._client.table("conversation_messages")
                .select("id")
                .in_("conversation_id", conversation_ids)
                .execute()
            ).data or []
            message_ids = [str(message["id"]) for message in messages]
            if message_ids:
                (
                    self._client.table("message_citations")
                    .delete()
                    .in_("message_id", message_ids)
                    .execute()
                )
            self._client.table("conversations").delete().eq(
                "workspace_id", str(workspace_id)
            ).execute()

        self._client.table("workspaces").delete().eq("id", str(workspace_id)).execute()

        paths_by_bucket: dict[str, list[str]] = {}
        for document in documents:
            bucket = str(document.get("storage_bucket") or "knowtrace-assets")
            paths = [str(document["storage_path"])]
            metadata_value = document.get("metadata")
            metadata = metadata_value if isinstance(metadata_value, dict) else {}
            extracted_text_path = metadata.get("extractedTextPath")
            if isinstance(extracted_text_path, str):
                paths.append(extracted_text_path)
            paths_by_bucket.setdefault(bucket, []).extend(paths)

        for bucket, paths in paths_by_bucket.items():
            try:
                self._client.storage.from_(bucket).remove(paths)
            except Exception:
                # Database records have already been deleted. A later bucket cleanup is safe.
                continue

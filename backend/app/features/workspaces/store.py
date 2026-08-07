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

    def list_workspaces(self) -> list[dict[str, Any]]:
        response = (
            self._client.table("workspaces").select("*").order("updated_at", desc=True).execute()
        )
        return response.data or []

    def get_workspace(self, workspace_id: UUID) -> dict[str, Any]:
        response = (
            self._client.table("workspaces").select("*").eq("id", str(workspace_id)).execute()
        )
        if not response.data:
            raise ApiError(404, "WORKSPACE_NOT_FOUND", "未找到对应的工作区。")
        return response.data[0]

    def update_workspace(self, workspace_id: UUID, data: dict[str, Any]) -> dict[str, Any]:
        response = (
            self._client.table("workspaces").update(data).eq("id", str(workspace_id)).execute()
        )
        if not response.data:
            raise ApiError(404, "WORKSPACE_NOT_FOUND", "未找到对应的工作区。")
        return response.data[0]

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from supabase import Client

from app.core.errors import ApiError


class SupabaseConversationStore:
    def __init__(self, client: Client) -> None:
        self._client = client

    def workspace_exists(self, workspace_id: UUID) -> bool:
        response = (
            self._client.table("workspaces").select("id").eq("id", str(workspace_id)).execute()
        )
        return bool(response.data)

    def create_conversation(self, data: dict[str, Any]) -> dict[str, Any]:
        response = self._client.table("conversations").insert(data).execute()
        if not response.data:
            raise ApiError(502, "CONVERSATION_CREATE_FAILED", "对话创建失败。")
        return response.data[0]

    def list_conversations(self, workspace_id: UUID) -> list[dict[str, Any]]:
        response = (
            self._client.table("conversations")
            .select("*")
            .eq("workspace_id", str(workspace_id))
            .order("updated_at", desc=True)
            .execute()
        )
        return response.data or []

    def get_conversation(self, workspace_id: UUID, conversation_id: UUID) -> dict[str, Any]:
        response = (
            self._client.table("conversations")
            .select("*")
            .eq("id", str(conversation_id))
            .eq("workspace_id", str(workspace_id))
            .execute()
        )
        if not response.data:
            raise ApiError(404, "CONVERSATION_NOT_FOUND", "未找到当前工作区中的对话。")
        return response.data[0]

    def next_sequence(self, conversation_id: UUID) -> int:
        response = (
            self._client.table("conversation_messages")
            .select("sequence")
            .eq("conversation_id", str(conversation_id))
            .order("sequence", desc=True)
            .limit(1)
            .execute()
        )
        return int(response.data[0]["sequence"]) + 1 if response.data else 0

    def create_message(self, data: dict[str, Any]) -> dict[str, Any]:
        response = self._client.table("conversation_messages").insert(data).execute()
        if not response.data:
            raise ApiError(502, "MESSAGE_CREATE_FAILED", "对话消息保存失败。")
        return response.data[0]

    def touch_conversation(self, conversation_id: UUID) -> None:
        self._client.table("conversations").update(
            {"updated_at": datetime.now(UTC).isoformat()}
        ).eq("id", str(conversation_id)).execute()

    def create_citations(self, rows: list[dict[str, Any]]) -> None:
        if rows:
            self._client.table("message_citations").insert(rows).execute()

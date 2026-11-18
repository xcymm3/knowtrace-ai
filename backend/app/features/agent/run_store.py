from typing import Any
from uuid import UUID

from postgrest.exceptions import APIError
from supabase import Client

from app.core.errors import ApiError
from app.features.agent.runs import Claim, Row


def _rows(query: Any, *, allow_conflict: bool = False) -> list[Row]:
    try:
        return query.execute().data
    except APIError as error:
        if allow_conflict and error.code == "23505":
            return []
        if error.code in {"PGRST205", "PGRST204", "42P01", "42703"}:
            raise ApiError(
                503,
                "AGENT_SCHEMA_UNAVAILABLE",
                "托管服务缺少 Agent 数据表或审批历史字段。请应用 Agent 数据库迁移后重试。",
            ) from error
        raise


class SupabaseRunStore:
    def __init__(self, client: Client) -> None:
        self._client = client

    def insert(self, data: Row) -> Row | None:
        rows = _rows(self._client.table("agent_runs").insert(data), allow_conflict=True)
        return rows[0] if rows else None

    def list(self, workspace_id: UUID) -> list[Row]:
        return _rows(
            self._client.table("agent_runs")
            .select("id,executor_id,task,status,revision,created_at")
            .eq("workspace_id", str(workspace_id))
            .order("created_at", desc=True)
            .limit(30)
        )

    def get(self, workspace_id: UUID, run_id: UUID) -> Row | None:
        rows = _rows(
            self._client.table("agent_runs")
            .select("*")
            .eq("workspace_id", str(workspace_id))
            .eq("id", str(run_id))
            .limit(1)
        )
        return rows[0] if rows else None

    def claimed(self, workspace_id: UUID, claim: Claim) -> Row | None:
        rows = _rows(
            self._client.table("agent_runs")
            .select("*")
            .eq("workspace_id", str(workspace_id))
            .eq("executor_id", str(claim.executor_id))
            .eq("claim_id", str(claim.claim_id))
            .limit(1)
        )
        return rows[0] if rows else None

    def queued(self, workspace_id: UUID, executor_id: UUID) -> Row | None:
        rows = _rows(
            self._client.table("agent_runs")
            .select("*")
            .eq("workspace_id", str(workspace_id))
            .eq("executor_id", str(executor_id))
            .eq("status", "QUEUED")
            .order("created_at")
            .limit(1)
        )
        return rows[0] if rows else None

    def update(self, row: Row, fields: Row) -> Row | None:
        rows = _rows(
            self._client.table("agent_runs")
            .update({**fields, "revision": row["revision"] + 1})
            .eq("workspace_id", row["workspace_id"])
            .eq("id", row["id"])
            .eq("revision", row["revision"]),
            allow_conflict=True,
        )
        return rows[0] if rows else None

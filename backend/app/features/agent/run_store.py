from uuid import UUID

from postgrest.exceptions import APIError
from supabase import Client

from app.features.agent.runs import Claim, Row


class SupabaseRunStore:
    def __init__(self, client: Client) -> None:
        self._client = client

    def insert(self, data: Row) -> Row | None:
        try:
            rows = self._client.table("agent_runs").insert(data).execute().data
        except APIError as error:
            if error.code == "23505":
                return None
            raise
        return rows[0] if rows else None

    def list(self, workspace_id: UUID) -> list[Row]:
        return (
            self._client.table("agent_runs")
            .select("id,executor_id,task,status,revision,created_at")
            .eq("workspace_id", str(workspace_id))
            .order("created_at", desc=True)
            .limit(30)
            .execute()
            .data
        )

    def get(self, workspace_id: UUID, run_id: UUID) -> Row | None:
        rows = (
            self._client.table("agent_runs")
            .select("*")
            .eq("workspace_id", str(workspace_id))
            .eq("id", str(run_id))
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def claimed(self, workspace_id: UUID, claim: Claim) -> Row | None:
        rows = (
            self._client.table("agent_runs")
            .select("*")
            .eq("workspace_id", str(workspace_id))
            .eq("executor_id", str(claim.executor_id))
            .eq("claim_id", str(claim.claim_id))
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def queued(self, workspace_id: UUID, executor_id: UUID) -> Row | None:
        rows = (
            self._client.table("agent_runs")
            .select("*")
            .eq("workspace_id", str(workspace_id))
            .eq("executor_id", str(executor_id))
            .eq("status", "QUEUED")
            .order("created_at")
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def update(self, row: Row, fields: Row) -> Row | None:
        try:
            rows = (
                self._client.table("agent_runs")
                .update({**fields, "revision": row["revision"] + 1})
                .eq("workspace_id", row["workspace_id"])
                .eq("id", row["id"])
                .eq("revision", row["revision"])
                .execute()
                .data
            )
        except APIError as error:
            if error.code == "23505":
                return None
            raise
        return rows[0] if rows else None

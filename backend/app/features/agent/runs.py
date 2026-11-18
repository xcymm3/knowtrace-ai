from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import ApiError

RunStatus = Literal[
    "QUEUED", "RUNNING", "WAITING_APPROVAL", "APPLYING", "SUCCEEDED", "FAILED", "CANCELLED"
]
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}
MAX_DIFF = 150_000


class RunCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: UUID
    executor_id: UUID
    task: str = Field(min_length=1, max_length=8000)


class RunSummary(BaseModel):
    id: UUID
    executor_id: UUID
    task: str
    status: RunStatus
    revision: int
    created_at: datetime


class RunEvent(BaseModel):
    kind: Literal["tool_start", "tool_end", "tool_error", "message", "error"]
    text: str = Field(min_length=1, max_length=16_000)


class Approval(BaseModel):
    id: UUID
    path: str = Field(min_length=1, max_length=512)
    diff: str = Field(min_length=1, max_length=MAX_DIFF)
    status: Literal["pending", "approved", "rejected", "applying", "applied", "failed", "cancelled"]
    decision: bool | None = None
    change_id: UUID | None = None
    error: str | None = None


class RunSnapshot(RunSummary):
    approval: Approval | None
    events: list[RunEvent]
    cancel_requested: bool


class Claim(BaseModel):
    executor_id: UUID
    claim_id: UUID


class Decision(BaseModel):
    approval_id: UUID
    approved: bool


class _Operation(BaseModel):
    claim_id: UUID
    op_id: UUID


class ReportEvent(_Operation):
    action: Literal["event"] = "event"
    event: RunEvent


class Preview(_Operation):
    action: Literal["preview"] = "preview"
    approval_id: UUID
    path: str = Field(min_length=1, max_length=512)
    diff: str = Field(min_length=1, max_length=MAX_DIFF)


class BeginWrite(_Operation):
    action: Literal["begin_write"] = "begin_write"
    approval_id: UUID


class FinishWrite(_Operation):
    action: Literal["finish_write"] = "finish_write"
    approval_id: UUID
    change_id: UUID | None = None
    error: str | None = Field(default=None, max_length=500)


class FinishRun(_Operation):
    action: Literal["finish"] = "finish"
    error: str | None = Field(default=None, max_length=500)


ExecutorOperation = Annotated[
    ReportEvent | Preview | BeginWrite | FinishWrite | FinishRun, Field(discriminator="action")
]
Row = dict[str, Any]


class RunStore(Protocol):
    def insert(self, data: Row) -> Row | None: ...
    def list(self, workspace_id: UUID) -> list[Row]: ...
    def get(self, workspace_id: UUID, run_id: UUID) -> Row | None: ...
    def claimed(self, workspace_id: UUID, claim: Claim) -> Row | None: ...
    def queued(self, workspace_id: UUID, executor_id: UUID) -> Row | None: ...
    def update(self, row: Row, fields: Row) -> Row | None: ...


def _conflict(message: str) -> ApiError:
    return ApiError(409, "AGENT_STATE_CONFLICT", message)


class AgentRuns:
    def __init__(self, store: RunStore) -> None:
        self.store = store

    def create(self, workspace_id: UUID, payload: RunCreate) -> Row:
        row = self.store.insert(
            {"workspace_id": str(workspace_id), **payload.model_dump(mode="json")}
        )
        if row is not None:
            return row
        existing = self.get(workspace_id, payload.id)
        if existing["task"] != payload.task or existing["executor_id"] != str(payload.executor_id):
            raise _conflict("该任务 ID 已被使用。")
        return existing

    def get(self, workspace_id: UUID, run_id: UUID) -> Row:
        row = self.store.get(workspace_id, run_id)
        if row is None:
            raise ApiError(404, "AGENT_RUN_NOT_FOUND", "未找到 Agent 任务。")
        return row

    def claim(self, workspace_id: UUID, claim: Claim) -> Row | None:
        existing = self.store.claimed(workspace_id, claim)
        if existing is not None:
            return existing
        queued = self.store.queued(workspace_id, claim.executor_id)
        if queued is None:
            return None
        return self.store.update(
            queued, {"status": "RUNNING", "claim_id": str(claim.claim_id)}
        ) or (self.store.claimed(workspace_id, claim))

    def _mutate(self, workspace_id: UUID, run_id: UUID, change: Callable[[Row], Row | None]) -> Row:
        for _ in range(8):
            current = self.get(workspace_id, run_id)
            fields = change(current)
            if fields is None:
                return current
            updated = self.store.update(current, fields)
            if updated is not None:
                return updated
        raise _conflict("任务状态正在变化，请重试。")

    def decide(self, workspace_id: UUID, run_id: UUID, decision: Decision) -> Row:
        def change(row: Row) -> Row | None:
            approval = row["approval"]
            if not approval or approval["id"] != str(decision.approval_id):
                raise _conflict("该待审批变更已失效。")
            if approval["decision"] is decision.approved:
                return None
            if row["status"] != "WAITING_APPROVAL" or approval["status"] != "pending":
                raise _conflict("该变更已处理或任务已取消。")
            return {
                "approval": {
                    **approval,
                    "decision": decision.approved,
                    "status": "approved" if decision.approved else "rejected",
                },
                "status": "WAITING_APPROVAL" if decision.approved else "RUNNING",
            }

        return self._mutate(workspace_id, run_id, change)

    def cancel(self, workspace_id: UUID, run_id: UUID) -> Row:
        def change(row: Row) -> Row | None:
            if row["status"] in TERMINAL or row["cancel_requested"]:
                return None
            if row["status"] == "APPLYING":
                return {"cancel_requested": True}
            fields: Row = {"status": "CANCELLED", "cancel_requested": True}
            if row["status"] == "WAITING_APPROVAL":
                fields["approval"] = {**row["approval"], "status": "cancelled"}
            return fields

        return self._mutate(workspace_id, run_id, change)

    def execute(self, workspace_id: UUID, run_id: UUID, op: ExecutorOperation) -> Row:
        def change(row: Row) -> Row | None:
            if row["claim_id"] != str(op.claim_id):
                raise _conflict("该任务的执行器凭证已失效。")
            if str(op.op_id) in row["executor_ops"]:
                return None
            if row["status"] == "CANCELLED":
                return None
            fields = self._operation(row, op)
            return {**fields, "executor_ops": [*row["executor_ops"], str(op.op_id)][-128:]}

        return self._mutate(workspace_id, run_id, change)

    @staticmethod
    def _operation(row: Row, op: ExecutorOperation) -> Row:
        status = row["status"]
        approval = row["approval"]
        if isinstance(op, ReportEvent) and status == "RUNNING":
            return {"events": [*row["events"], op.event.model_dump()][-100:]}
        if isinstance(op, Preview) and status == "RUNNING" and approval is None:
            pending = Approval(id=op.approval_id, path=op.path, diff=op.diff, status="pending")
            return {"status": "WAITING_APPROVAL", "approval": pending.model_dump(mode="json")}
        if (
            isinstance(op, (BeginWrite, FinishWrite))
            and approval
            and approval["id"] == str(op.approval_id)
        ):
            if isinstance(op, BeginWrite) and status == "WAITING_APPROVAL":
                if approval["status"] == "approved":
                    return {
                        "status": "APPLYING",
                        "approval": {**approval, "status": "applying"},
                    }
            if isinstance(op, FinishWrite) and status == "APPLYING":
                return {
                    "status": "CANCELLED" if row["cancel_requested"] else "RUNNING",
                    "approval": {
                        **approval,
                        "status": "applied" if op.change_id else "failed",
                        "change_id": str(op.change_id) if op.change_id else None,
                        "error": op.error,
                    },
                }
        if isinstance(op, FinishRun) and status in {"RUNNING", "WAITING_APPROVAL"}:
            failed = op.error or (approval and approval["status"] == "failed")
            fields: Row = {"status": "FAILED" if failed else "SUCCEEDED"}
            if op.error:
                fields["events"] = [*row["events"], {"kind": "error", "text": op.error}][-100:]
            if status == "WAITING_APPROVAL":
                fields["approval"] = {**approval, "status": "failed", "error": op.error}
            return fields
        raise _conflict("任务或审批状态已变化。")

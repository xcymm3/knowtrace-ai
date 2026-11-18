import asyncio
from collections.abc import AsyncIterator
from functools import lru_cache
from hashlib import sha256
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.api.auth import get_owned_workspace_id
from app.core.config import get_settings
from app.core.errors import ApiError
from app.features.agent.edits import journal_path
from app.features.agent.local_store import LOCAL_EXECUTOR_ID, LocalRunStore
from app.features.agent.run_store import SupabaseRunStore
from app.features.agent.runs import (
    TERMINAL,
    AgentRuns,
    Claim,
    Decision,
    ExecutorOperation,
    RunCreate,
    RunSnapshot,
    RunSummary,
)
from app.features.documents.store import create_supabase_client

router = APIRouter(prefix="/workspaces/{workspace_id}/agent/runs", tags=["agent"])
Workspace = Annotated[UUID, Depends(get_owned_workspace_id)]


@lru_cache
def get_agent_runs() -> AgentRuns:
    settings = get_settings()
    if settings.local_agent_root is not None:
        root = settings.local_agent_root.resolve()
        suffix = sha256(str(root).encode()).hexdigest()[:20]
        return AgentRuns(LocalRunStore(journal_path().parent / f"web-agent-{suffix}.sqlite3"))
    return AgentRuns(SupabaseRunStore(create_supabase_client(settings)))


Runs = Annotated[AgentRuns, Depends(get_agent_runs)]


@router.post("", response_model=RunSnapshot, status_code=201)
def create_run(payload: RunCreate, workspace_id: Workspace, runs: Runs):
    if isinstance(runs.store, LocalRunStore):
        payload = payload.model_copy(update={"executor_id": LOCAL_EXECUTOR_ID})
    return runs.create(workspace_id, payload)


@router.get("", response_model=list[RunSummary])
def list_runs(workspace_id: Workspace, runs: Runs):
    return runs.store.list(workspace_id)


@router.get("/config")
def run_config(workspace_id: Workspace):
    root = get_settings().local_agent_root
    return {"mode": "local", "directory": root.name} if root else {"mode": "remote"}


@router.post("/claim", response_model=RunSnapshot | None)
def claim_run(payload: Claim, workspace_id: Workspace, runs: Runs):
    if isinstance(runs.store, LocalRunStore):
        raise ApiError(403, "AGENT_LOCAL_EXECUTOR", "本地任务由工作台执行器领取。")
    return runs.claim(workspace_id, payload)


@router.get("/{run_id}", response_model=RunSnapshot)
def get_run(run_id: UUID, workspace_id: Workspace, runs: Runs):
    return runs.get(workspace_id, run_id)


@router.post("/{run_id}/decision", response_model=RunSnapshot)
def decide_run(run_id: UUID, payload: Decision, workspace_id: Workspace, runs: Runs):
    return runs.decide(workspace_id, run_id, payload)


@router.post("/{run_id}/cancel", response_model=RunSnapshot)
def cancel_run(run_id: UUID, workspace_id: Workspace, runs: Runs):
    return runs.cancel(workspace_id, run_id)


@router.post("/{run_id}/executor", response_model=RunSnapshot)
def update_run(run_id: UUID, payload: ExecutorOperation, workspace_id: Workspace, runs: Runs):
    if isinstance(runs.store, LocalRunStore):
        raise ApiError(403, "AGENT_LOCAL_EXECUTOR", "本地任务由工作台执行器更新。")
    return runs.execute(workspace_id, run_id, payload)


@router.get("/{run_id}/events")
async def watch_run(
    run_id: UUID,
    request: Request,
    workspace_id: Workspace,
    runs: Runs,
    after: Annotated[int, Query(ge=-1)] = -1,
) -> StreamingResponse:
    initial = await asyncio.to_thread(runs.get, workspace_id, run_id)

    async def snapshots() -> AsyncIterator[str]:
        row = initial
        revision = after
        for index in range(15):
            if await request.is_disconnected():
                return
            if row["revision"] > revision:
                revision = row["revision"]
                snapshot = RunSnapshot.model_validate(row).model_dump_json()
                yield f"id: {revision}\nevent: snapshot\ndata: {snapshot}\n\n"
            elif index % 5 == 0:
                yield ": keepalive\n\n"
            if row["status"] in TERMINAL or index == 14:
                return
            await asyncio.sleep(1)
            row = await asyncio.to_thread(runs.store.get, workspace_id, run_id)
            if row is None:
                return

    return StreamingResponse(
        snapshots(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )

from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from app.api.v1.agent import Runs, watch_run
from app.core.config import get_settings
from app.core.errors import ApiError
from app.features.agent.local_store import LOCAL_EXECUTOR_ID, LOCAL_WORKSPACE_ID, LocalRunStore
from app.features.agent.runs import Decision, Permission, RunCreate, RunSnapshot, RunSummary


def require_local_session(x_knowtrace_local: Annotated[str, Header()] = "") -> None:
    settings = get_settings()
    secret = settings.local_agent_token
    if settings.local_agent_root is None or secret is None:
        raise ApiError(503, "AGENT_NOT_LOCAL", "请使用 pnpm dev:local 启动本机 Agent。")
    expected = secret.get_secret_value().encode()
    if not expected or not compare_digest(x_knowtrace_local.encode(), expected):
        raise ApiError(403, "AGENT_LOCAL_ONLY", "请从 KnowTrace 本机工作台访问 Agent。")


router = APIRouter(
    prefix="/agent", tags=["local agent"], dependencies=[Depends(require_local_session)]
)


class LocalTask(RunCreate):
    thread_id: UUID
    permission: Permission = "project"


@router.get("/config")
def config():
    root = get_settings().local_agent_root
    return {"directory": str(root)}


@router.get("/threads", response_model=list[RunSummary])
def list_threads(runs: Runs):
    assert isinstance(runs.store, LocalRunStore)
    return runs.store.threads()


@router.get("/threads/{thread_id}", response_model=list[RunSnapshot])
def get_thread(thread_id: UUID, runs: Runs):
    assert isinstance(runs.store, LocalRunStore)
    return runs.store.thread(thread_id)


@router.post("/runs", response_model=RunSnapshot, status_code=201)
def start_run(payload: LocalTask, runs: Runs):
    if payload.id != payload.thread_id:
        anchor = runs.get(LOCAL_WORKSPACE_ID, payload.thread_id)
        if anchor.get("thread_id") != str(payload.thread_id):
            raise ApiError(404, "AGENT_THREAD_NOT_FOUND", "找不到该会话。")
    return runs.create(
        LOCAL_WORKSPACE_ID,
        RunCreate(id=payload.id, task=payload.task, executor_id=LOCAL_EXECUTOR_ID),
        thread_id=str(payload.thread_id),
        permission=payload.permission,
    )


@router.get("/runs/{run_id}", response_model=RunSnapshot)
def get_run(run_id: UUID, runs: Runs):
    return runs.get(LOCAL_WORKSPACE_ID, run_id)


@router.post("/runs/{run_id}/decision", response_model=RunSnapshot)
def decide_run(run_id: UUID, payload: Decision, runs: Runs):
    return runs.decide(LOCAL_WORKSPACE_ID, run_id, payload)


@router.post("/runs/{run_id}/cancel", response_model=RunSnapshot)
def cancel_run(run_id: UUID, runs: Runs):
    return runs.cancel(LOCAL_WORKSPACE_ID, run_id)


@router.get("/runs/{run_id}/events")
async def events(run_id: UUID, request: Request, runs: Runs, after: int = -1):
    return await watch_run(run_id, request, LOCAL_WORKSPACE_ID, runs, after)

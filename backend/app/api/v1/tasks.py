import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.auth import CurrentUser, get_current_user, get_owned_workspace_id
from app.api.dependencies import get_task_control_service, get_task_store, get_workspace_service
from app.features.tasks.schemas import TaskStatusResponse
from app.features.tasks.service import TaskControlService
from app.features.tasks.store import SupabaseTaskStore
from app.features.workspaces.service import WorkspaceService

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def _get_task_snapshot(store: SupabaseTaskStore, task_id: UUID) -> TaskStatusResponse:
    task = await anyio.to_thread.run_sync(store.get_task, task_id)
    return TaskStatusResponse.model_validate(task)


async def get_owned_task_id(
    task_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    store: SupabaseTaskStore = Depends(get_task_store),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> UUID:
    snapshot = await _get_task_snapshot(store, task_id)
    await workspace_service.get_workspace(snapshot.workspace_id, current_user.id)
    return task_id


@router.get("/{task_id}", response_model=TaskStatusResponse, summary="Read background task state")
async def get_task(
    task_id: UUID = Depends(get_owned_task_id),
    store: SupabaseTaskStore = Depends(get_task_store),
) -> TaskStatusResponse:
    return await _get_task_snapshot(store, task_id)


@router.post("/{task_id}/retry", response_model=TaskStatusResponse, summary="Retry a failed task")
async def retry_task(
    task_id: UUID = Depends(get_owned_task_id),
    store: SupabaseTaskStore = Depends(get_task_store),
    service: TaskControlService = Depends(get_task_control_service),
) -> TaskStatusResponse:
    task = await _get_task_snapshot(store, task_id)
    retried = await service.retry_task(task.workspace_id, task_id)
    return TaskStatusResponse.model_validate(retried)


@router.post("/{task_id}/cancel", response_model=TaskStatusResponse, summary="Cancel a queued task")
async def cancel_task(
    task_id: UUID = Depends(get_owned_task_id),
    store: SupabaseTaskStore = Depends(get_task_store),
    service: TaskControlService = Depends(get_task_control_service),
) -> TaskStatusResponse:
    task = await _get_task_snapshot(store, task_id)
    cancelled = await service.cancel_task(task.workspace_id, task_id)
    return TaskStatusResponse.model_validate(cancelled)


@router.get(
    "/workspaces/{workspace_id}",
    response_model=list[TaskStatusResponse],
    summary="List workspace tasks",
)
async def list_workspace_tasks(
    workspace_id: UUID = Depends(get_owned_workspace_id),
    store: SupabaseTaskStore = Depends(get_task_store),
) -> list[TaskStatusResponse]:
    tasks = await anyio.to_thread.run_sync(store.list_workspace_tasks, workspace_id)
    return [TaskStatusResponse.model_validate(task) for task in tasks]


async def task_event_stream(store: SupabaseTaskStore, task_id: UUID) -> AsyncIterator[str]:
    """Poll the task record for up to one minute and emit only changed snapshots."""
    previous_payload: str | None = None

    for _ in range(60):
        snapshot = await _get_task_snapshot(store, task_id)
        payload = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False)

        if payload != previous_payload:
            yield f"event: progress\ndata: {payload}\n\n"
            previous_payload = payload

        if snapshot.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            yield f"event: complete\ndata: {payload}\n\n"
            return

        await asyncio.sleep(1)

    yield 'event: timeout\ndata: {"message":"任务仍在执行，请重新连接。"}\n\n'


@router.get("/{task_id}/events", summary="Stream background task progress")
async def stream_task_events(
    task_id: UUID = Depends(get_owned_task_id),
    store: SupabaseTaskStore = Depends(get_task_store),
) -> StreamingResponse:
    return StreamingResponse(
        task_event_stream(store, task_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

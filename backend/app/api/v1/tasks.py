import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_task_store
from app.features.tasks.schemas import TaskStatusResponse
from app.features.tasks.store import SupabaseTaskStore

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def _get_task_snapshot(store: SupabaseTaskStore, task_id: UUID) -> TaskStatusResponse:
    task = await anyio.to_thread.run_sync(store.get_task, task_id)
    return TaskStatusResponse.model_validate(task)


@router.get("/{task_id}", response_model=TaskStatusResponse, summary="Read background task state")
async def get_task(
    task_id: UUID,
    store: SupabaseTaskStore = Depends(get_task_store),
) -> TaskStatusResponse:
    return await _get_task_snapshot(store, task_id)


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
    task_id: UUID,
    store: SupabaseTaskStore = Depends(get_task_store),
) -> StreamingResponse:
    return StreamingResponse(
        task_event_stream(store, task_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import UUID

from app.features.workspaces.schemas import WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate


class WorkspaceStore(Protocol):
    def create_workspace(self, data: dict[str, object]) -> dict[str, object]: ...
    def list_workspaces(self) -> list[dict[str, object]]: ...
    def get_workspace(self, workspace_id: UUID) -> dict[str, object]: ...
    def update_workspace(
        self, workspace_id: UUID, data: dict[str, object]
    ) -> dict[str, object]: ...
    def delete_workspace(self, workspace_id: UUID) -> None: ...


class WorkspaceService:
    def __init__(self, store: WorkspaceStore) -> None:
        self._store = store

    async def create_workspace(self, payload: WorkspaceCreate) -> WorkspaceResponse:
        record = await asyncio.to_thread(self._store.create_workspace, payload.model_dump())
        return WorkspaceResponse.model_validate(record)

    async def list_workspaces(self) -> list[WorkspaceResponse]:
        records = await asyncio.to_thread(self._store.list_workspaces)
        return [WorkspaceResponse.model_validate(record) for record in records]

    async def get_workspace(self, workspace_id: UUID) -> WorkspaceResponse:
        record = await asyncio.to_thread(self._store.get_workspace, workspace_id)
        return WorkspaceResponse.model_validate(record)

    async def update_workspace(
        self, workspace_id: UUID, payload: WorkspaceUpdate
    ) -> WorkspaceResponse:
        data = payload.model_dump(exclude_unset=True)
        if "status" in data:
            data["status"] = data["status"].value
        if not data:
            return await self.get_workspace(workspace_id)
        record = await asyncio.to_thread(self._store.update_workspace, workspace_id, data)
        return WorkspaceResponse.model_validate(record)

    async def delete_workspace(self, workspace_id: UUID) -> None:
        await asyncio.to_thread(self._store.delete_workspace, workspace_id)

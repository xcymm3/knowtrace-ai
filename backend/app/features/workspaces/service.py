from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import UUID

from app.features.workspaces.schemas import WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate


class WorkspaceStore(Protocol):
    def create_workspace(self, data: dict[str, object]) -> dict[str, object]: ...
    def list_workspaces(self, owner_id: UUID) -> list[dict[str, object]]: ...
    def get_workspace(self, workspace_id: UUID, owner_id: UUID) -> dict[str, object]: ...
    def update_workspace(
        self, workspace_id: UUID, owner_id: UUID, data: dict[str, object]
    ) -> dict[str, object]: ...
    def delete_workspace(self, workspace_id: UUID, owner_id: UUID) -> None: ...


class WorkspaceService:
    def __init__(self, store: WorkspaceStore) -> None:
        self._store = store

    async def create_workspace(self, payload: WorkspaceCreate, owner_id: UUID) -> WorkspaceResponse:
        data = {**payload.model_dump(), "owner_id": str(owner_id)}
        record = await asyncio.to_thread(self._store.create_workspace, data)
        return WorkspaceResponse.model_validate(record)

    async def list_workspaces(self, owner_id: UUID) -> list[WorkspaceResponse]:
        records = await asyncio.to_thread(self._store.list_workspaces, owner_id)
        return [WorkspaceResponse.model_validate(record) for record in records]

    async def get_workspace(self, workspace_id: UUID, owner_id: UUID) -> WorkspaceResponse:
        record = await asyncio.to_thread(self._store.get_workspace, workspace_id, owner_id)
        return WorkspaceResponse.model_validate(record)

    async def update_workspace(
        self, workspace_id: UUID, payload: WorkspaceUpdate, owner_id: UUID
    ) -> WorkspaceResponse:
        data = payload.model_dump(exclude_unset=True)
        if "status" in data:
            data["status"] = data["status"].value
        if not data:
            return await self.get_workspace(workspace_id, owner_id)
        record = await asyncio.to_thread(self._store.update_workspace, workspace_id, owner_id, data)
        return WorkspaceResponse.model_validate(record)

    async def delete_workspace(self, workspace_id: UUID, owner_id: UUID) -> None:
        await asyncio.to_thread(self._store.delete_workspace, workspace_id, owner_id)

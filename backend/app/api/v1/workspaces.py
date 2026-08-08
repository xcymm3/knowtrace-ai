from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_workspace_service
from app.features.workspaces.schemas import WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate
from app.features.workspaces.service import WorkspaceService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate,
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    return await service.create_workspace(payload)


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    service: WorkspaceService = Depends(get_workspace_service),
) -> list[WorkspaceResponse]:
    return await service.list_workspaces()


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: UUID,
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    return await service.get_workspace(workspace_id)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: UUID,
    payload: WorkspaceUpdate,
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    return await service.update_workspace(workspace_id, payload)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: UUID,
    service: WorkspaceService = Depends(get_workspace_service),
) -> None:
    await service.delete_workspace(workspace_id)

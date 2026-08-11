import asyncio
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, status

from app.api.auth import CurrentUser, get_current_user, get_owned_workspace_id
from app.api.dependencies import (
    get_document_ingestion_service,
    get_inline_task_queue,
    get_rag_conversation_service,
    get_task_store,
    get_workspace_service,
)
from app.features.conversations.service import RagConversationService
from app.features.documents.schemas import SourceDocumentResponse
from app.features.documents.service import DocumentIngestionService
from app.features.tasks.inline import InlineTaskQueue
from app.features.tasks.schemas import TaskStatusResponse
from app.features.tasks.store import SupabaseTaskStore
from app.features.workspaces.schemas import (
    WorkspaceCreate,
    WorkspaceOverviewResponse,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from app.features.workspaces.service import WorkspaceService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate,
    current_user: CurrentUser = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    return await service.create_workspace(payload, current_user.id)


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    current_user: CurrentUser = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
) -> list[WorkspaceResponse]:
    return await service.list_workspaces(current_user.id)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: UUID = Depends(get_owned_workspace_id),
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    return await service.get_workspace(workspace_id)


@router.get("/{workspace_id}/overview", response_model=WorkspaceOverviewResponse)
async def get_workspace_overview(
    workspace_id: UUID = Depends(get_owned_workspace_id),
    document_service: DocumentIngestionService = Depends(get_document_ingestion_service),
    task_store: SupabaseTaskStore = Depends(get_task_store),
    conversation_service: RagConversationService = Depends(get_rag_conversation_service),
) -> WorkspaceOverviewResponse:
    """Read every panel of one knowledge workspace in a single browser request."""
    # A prior Vercel request can be terminated after it has persisted a task.
    # Resume one stale task while loading the workspace, rather than leaving
    # the user with a permanently spinning "正在解析" status.
    inline_queue: InlineTaskQueue | None = get_inline_task_queue()
    if inline_queue:
        await inline_queue.resume_workspace_tasks(workspace_id)
    documents, tasks, conversations = await asyncio.gather(
        document_service.list_documents(workspace_id),
        anyio.to_thread.run_sync(task_store.list_workspace_tasks, workspace_id),
        conversation_service.list_conversations(workspace_id),
    )
    return WorkspaceOverviewResponse(
        documents=[SourceDocumentResponse.model_validate(document) for document in documents],
        tasks=[TaskStatusResponse.model_validate(task) for task in tasks],
        conversations=conversations,
    )


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    payload: WorkspaceUpdate,
    workspace_id: UUID = Depends(get_owned_workspace_id),
    current_user: CurrentUser = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    return await service.update_workspace(workspace_id, payload, current_user.id)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: UUID = Depends(get_owned_workspace_id),
    current_user: CurrentUser = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
) -> None:
    await service.delete_workspace(workspace_id, current_user.id)

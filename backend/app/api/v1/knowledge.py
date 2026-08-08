from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.auth import get_owned_workspace_id
from app.api.dependencies import get_knowledge_search_service
from app.features.knowledge.schemas import KnowledgeSearchRequest, KnowledgeSearchResponse
from app.features.knowledge.service import KnowledgeSearchService

router = APIRouter(prefix="/workspaces/{workspace_id}/search", tags=["knowledge"])


@router.post("", response_model=KnowledgeSearchResponse, summary="Search research knowledge")
async def search_knowledge(
    request: KnowledgeSearchRequest,
    workspace_id: UUID = Depends(get_owned_workspace_id),
    service: KnowledgeSearchService = Depends(get_knowledge_search_service),
) -> KnowledgeSearchResponse:
    """Return traceable sources inside one KnowTrace workspace."""
    return await service.search(workspace_id, request)

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import get_knowledge_search_service
from app.features.knowledge.schemas import KnowledgeSearchRequest, KnowledgeSearchResponse
from app.features.knowledge.service import KnowledgeSearchService

router = APIRouter(prefix="/projects/{project_id}/search", tags=["knowledge"])


@router.post("", response_model=KnowledgeSearchResponse, summary="Search research knowledge")
async def search_knowledge(
    project_id: UUID,
    request: KnowledgeSearchRequest,
    service: KnowledgeSearchService = Depends(get_knowledge_search_service),
) -> KnowledgeSearchResponse:
    """Return traceable sources used for an evidence-grounded selection decision."""
    return await service.search(project_id, request)

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_project_service
from app.features.projects.schemas import (
    ProductComparisonResponse,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
    ResearchProjectCreate,
    ResearchProjectResponse,
    ResearchProjectUpdate,
)
from app.features.projects.service import ProjectService

router = APIRouter(tags=["projects"])


@router.post(
    "/projects", response_model=ResearchProjectResponse, status_code=status.HTTP_201_CREATED
)
async def create_project(
    payload: ResearchProjectCreate,
    service: ProjectService = Depends(get_project_service),
) -> ResearchProjectResponse:
    return await service.create_project(payload)


@router.get("/projects", response_model=list[ResearchProjectResponse])
async def list_projects(
    service: ProjectService = Depends(get_project_service),
) -> list[ResearchProjectResponse]:
    return await service.list_projects()


@router.get("/projects/{project_id}", response_model=ResearchProjectResponse)
async def get_project(
    project_id: UUID, service: ProjectService = Depends(get_project_service)
) -> ResearchProjectResponse:
    return await service.get_project(project_id)


@router.patch("/projects/{project_id}", response_model=ResearchProjectResponse)
async def update_project(
    project_id: UUID,
    payload: ResearchProjectUpdate,
    service: ProjectService = Depends(get_project_service),
) -> ResearchProjectResponse:
    return await service.update_project(project_id, payload)


@router.post(
    "/projects/{project_id}/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_product(
    project_id: UUID,
    payload: ProductCreate,
    service: ProjectService = Depends(get_project_service),
) -> ProductResponse:
    return await service.create_product(project_id, payload)


@router.get("/projects/{project_id}/products", response_model=list[ProductResponse])
async def list_products(
    project_id: UUID, service: ProjectService = Depends(get_project_service)
) -> list[ProductResponse]:
    return await service.list_products(project_id)


@router.patch("/projects/{project_id}/products/{product_id}", response_model=ProductResponse)
async def update_product(
    project_id: UUID,
    product_id: UUID,
    payload: ProductUpdate,
    service: ProjectService = Depends(get_project_service),
) -> ProductResponse:
    return await service.update_product(project_id, product_id, payload)


@router.get("/projects/{project_id}/comparison", response_model=ProductComparisonResponse)
async def compare_products(
    project_id: UUID, service: ProjectService = Depends(get_project_service)
) -> ProductComparisonResponse:
    return await service.compare_products(project_id)

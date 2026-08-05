from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_report_service
from app.features.reports.schemas import (
    ReviewFeedbackCreate,
    ReviewFeedbackResponse,
    SelectionReportCreate,
    SelectionReportResponse,
)
from app.features.reports.service import ReportService

router = APIRouter(tags=["reports"])


@router.post(
    "/projects/{project_id}/reports",
    response_model=SelectionReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_report(
    project_id: UUID,
    payload: SelectionReportCreate,
    service: ReportService = Depends(get_report_service),
) -> SelectionReportResponse:
    return await service.create_report(project_id, payload)


@router.get("/projects/{project_id}/reports", response_model=list[SelectionReportResponse])
async def list_reports(
    project_id: UUID, service: ReportService = Depends(get_report_service)
) -> list[SelectionReportResponse]:
    return await service.list_reports(project_id)


@router.get("/projects/{project_id}/reports/{report_id}", response_model=SelectionReportResponse)
async def get_report(
    project_id: UUID,
    report_id: UUID,
    service: ReportService = Depends(get_report_service),
) -> SelectionReportResponse:
    return await service.get_report(project_id, report_id)


@router.post(
    "/projects/{project_id}/reports/{report_id}/feedback",
    response_model=ReviewFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_feedback(
    project_id: UUID,
    report_id: UUID,
    payload: ReviewFeedbackCreate,
    service: ReportService = Depends(get_report_service),
) -> ReviewFeedbackResponse:
    return await service.create_feedback(project_id, report_id, payload)

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.features.documents.schemas import DocumentKind


class ReportStatus(StrEnum):
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class FindingType(StrEnum):
    RECOMMENDATION = "RECOMMENDATION"
    DIFFERENTIATOR = "DIFFERENTIATOR"
    RISK = "RISK"
    AUDIENCE_INSIGHT = "AUDIENCE_INSIGHT"
    CONTENT_STRATEGY = "CONTENT_STRATEGY"


class ReviewDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_REVISION = "NEEDS_REVISION"


class SelectionReportCreate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    product_ids: list[UUID] = Field(default_factory=list, max_length=30)


class FindingCitationResponse(BaseModel):
    id: UUID
    chunk_id: UUID
    excerpt: str
    position: int
    document_id: UUID
    file_name: str
    kind: DocumentKind
    product_id: UUID | None


class ReportFindingResponse(BaseModel):
    id: UUID
    type: FindingType
    title: str
    content: str
    confidence: float | None
    position: int
    citations: list[FindingCitationResponse]


class SelectionReportResponse(BaseModel):
    id: UUID
    project_id: UUID
    task_id: UUID | None
    title: str
    summary: str | None
    status: ReportStatus
    generation_metadata: dict[str, object]
    created_at: str
    updated_at: str
    findings: list[ReportFindingResponse]


class ReviewFeedbackCreate(BaseModel):
    decision: ReviewDecision
    comment: str | None = Field(default=None, max_length=2000)
    finding_id: UUID | None = None
    reviewer_label: str = Field(default="MVP Reviewer", min_length=1, max_length=120)


class ReviewFeedbackResponse(BaseModel):
    id: UUID
    report_id: UUID
    finding_id: UUID | None
    decision: ReviewDecision
    comment: str | None
    reviewer_label: str
    created_at: str

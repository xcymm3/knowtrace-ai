from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentKind(StrEnum):
    PRODUCT_SHEET = "PRODUCT_SHEET"
    COMPETITOR_SHEET = "COMPETITOR_SHEET"
    BRAND_GUIDE = "BRAND_GUIDE"
    PLATFORM_RULE = "PLATFORM_RULE"
    REVIEW_EXPORT = "REVIEW_EXPORT"
    PRODUCT_IMAGE = "PRODUCT_IMAGE"
    COMPETITOR_SCREENSHOT = "COMPETITOR_SCREENSHOT"
    OTHER = "OTHER"


class DocumentUploadResponse(BaseModel):
    id: UUID
    project_id: UUID
    product_id: UUID | None
    kind: DocumentKind
    file_name: str
    status: str
    task_id: UUID
    task_status: str


class SourceDocumentResponse(BaseModel):
    id: UUID
    project_id: UUID
    product_id: UUID | None
    kind: DocumentKind
    file_name: str
    mime_type: str
    size_bytes: int
    status: str
    error_message: str | None
    metadata: dict[str, object]
    created_at: str
    updated_at: str


class ParsedDocumentPreview(BaseModel):
    text: str = Field(
        description="Deterministically extracted text; OCR is deferred for image-only files."
    )
    metadata: dict[str, object]
    needs_ocr: bool

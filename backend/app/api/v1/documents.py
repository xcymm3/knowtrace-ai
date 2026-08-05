from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api.dependencies import get_document_ingestion_service
from app.features.documents.schemas import DocumentKind, DocumentUploadResponse
from app.features.documents.service import DocumentIngestionService, UploadInput

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload research material",
)
async def upload_document(
    project_id: UUID,
    file: UploadFile = File(description="TXT, CSV, XLSX, PDF, JPG, PNG or WEBP research material."),
    kind: DocumentKind = Form(),
    product_id: UUID | None = Form(default=None),
    service: DocumentIngestionService = Depends(get_document_ingestion_service),
) -> DocumentUploadResponse:
    content = await file.read()
    await file.close()

    return await service.ingest(
        UploadInput(
            project_id=project_id,
            product_id=product_id,
            kind=kind,
            file_name=file.filename or "uploaded-file",
            mime_type=file.content_type or "application/octet-stream",
            content=content,
        )
    )

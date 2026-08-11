from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api.auth import get_owned_workspace_id
from app.api.dependencies import get_document_ingestion_service, get_task_control_service
from app.features.documents.schemas import (
    DocumentKind,
    DocumentUploadResponse,
    SourceDocumentResponse,
)
from app.features.documents.service import DocumentIngestionService, UploadInput
from app.features.tasks.service import TaskControlService

router = APIRouter(prefix="/workspaces/{workspace_id}/documents", tags=["documents"])


@router.get("", response_model=list[SourceDocumentResponse], summary="List workspace documents")
async def list_documents(
    workspace_id: UUID = Depends(get_owned_workspace_id),
    service: DocumentIngestionService = Depends(get_document_ingestion_service),
) -> list[SourceDocumentResponse]:
    documents = await service.list_documents(workspace_id)
    return [SourceDocumentResponse.model_validate(document) for document in documents]


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a knowledge document",
)
async def upload_document(
    workspace_id: UUID = Depends(get_owned_workspace_id),
    file: UploadFile = File(
        description=(
            "TXT, Markdown, CSV, XLS, XLSX, DOC, DOCX, PDF, JPG, PNG or WEBP knowledge material."
        )
    ),
    kind: DocumentKind = Form(default=DocumentKind.GENERAL),
    service: DocumentIngestionService = Depends(get_document_ingestion_service),
) -> DocumentUploadResponse:
    content = await file.read()
    await file.close()

    return await service.ingest(
        UploadInput(
            workspace_id=workspace_id,
            kind=kind,
            file_name=file.filename or "uploaded-file",
            mime_type=file.content_type or "application/octet-stream",
            content=content,
        )
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and its index",
)
async def delete_document(
    document_id: UUID,
    workspace_id: UUID = Depends(get_owned_workspace_id),
    service: TaskControlService = Depends(get_task_control_service),
) -> None:
    await service.delete_document(workspace_id, document_id)

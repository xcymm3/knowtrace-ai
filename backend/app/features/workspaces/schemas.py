from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.features.conversations.schemas import ConversationResponse
from app.features.documents.schemas import SourceDocumentResponse
from app.features.tasks.schemas import TaskStatusResponse


class WorkspaceStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    status: WorkspaceStatus | None = None


class WorkspaceResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    status: WorkspaceStatus
    created_at: str
    updated_at: str


class WorkspaceOverviewResponse(BaseModel):
    documents: list[SourceDocumentResponse]
    tasks: list[TaskStatusResponse]
    conversations: list[ConversationResponse]

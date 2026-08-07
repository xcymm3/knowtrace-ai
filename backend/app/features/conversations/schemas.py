from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.features.knowledge.schemas import KnowledgeCitation


class ConversationRole(StrEnum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM = "SYSTEM"


class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=160)


class ConversationResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    title: str
    created_at: str
    updated_at: str


class RagQuestionRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    retrieval_limit: int = Field(default=6, ge=1, le=12)


class RagSource(BaseModel):
    chunk_id: UUID
    citation: KnowledgeCitation
    excerpt: str
    score: float


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    role: ConversationRole
    content: str
    sequence: int
    created_at: str

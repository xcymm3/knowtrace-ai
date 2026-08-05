from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.features.documents.schemas import DocumentKind


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=8, ge=1, le=20)
    document_kind: DocumentKind | None = None
    product_id: UUID | None = None


class KnowledgeCitation(BaseModel):
    document_id: UUID
    file_name: str
    kind: DocumentKind
    product_id: UUID | None = None
    chunk_index: int
    start_char: int | None = None
    end_char: int | None = None


class KnowledgeSearchHit(BaseModel):
    chunk_id: UUID
    content: str
    semantic_score: float
    keyword_score: float
    final_score: float
    citation: KnowledgeCitation


class KnowledgeSearchResponse(BaseModel):
    query: str
    hits: list[KnowledgeSearchHit]

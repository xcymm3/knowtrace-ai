from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import UUID

from app.features.knowledge.embeddings import EmbeddingProvider
from app.features.knowledge.schemas import (
    KnowledgeCitation,
    KnowledgeSearchHit,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)


class KnowledgeStore(Protocol):
    def search(
        self,
        project_id: UUID,
        query_embedding: list[float],
        query_text: str,
        limit: int,
        document_kind: str | None,
        product_id: UUID | None,
    ) -> list[dict[str, object]]: ...


class KnowledgeSearchService:
    def __init__(self, store: KnowledgeStore, embeddings: EmbeddingProvider) -> None:
        self._store = store
        self._embeddings = embeddings

    async def search(
        self, project_id: UUID, request: KnowledgeSearchRequest
    ) -> KnowledgeSearchResponse:
        vector = (await self._embeddings.embed([request.query]))[0]
        records = await asyncio.to_thread(
            self._store.search,
            project_id,
            vector,
            request.query,
            request.limit,
            request.document_kind.value if request.document_kind else None,
            request.product_id,
        )
        return KnowledgeSearchResponse(
            query=request.query,
            hits=[self._to_hit(record) for record in records],
        )

    @staticmethod
    def _to_hit(record: dict[str, object]) -> KnowledgeSearchHit:
        metadata = record.get("metadata")
        safe_metadata = metadata if isinstance(metadata, dict) else {}
        return KnowledgeSearchHit(
            chunk_id=record["id"],  # type: ignore[arg-type]
            content=str(record["content"]),
            semantic_score=float(record.get("semantic_score", 0)),
            keyword_score=float(record.get("keyword_score", 0)),
            final_score=float(record.get("final_score", 0)),
            citation=KnowledgeCitation(
                document_id=record["document_id"],  # type: ignore[arg-type]
                file_name=str(record["file_name"]),
                kind=record["kind"],  # type: ignore[arg-type]
                product_id=record.get("product_id"),  # type: ignore[arg-type]
                chunk_index=int(safe_metadata.get("chunkIndex", 0)),
                start_char=safe_metadata.get("startChar"),  # type: ignore[arg-type]
                end_char=safe_metadata.get("endChar"),  # type: ignore[arg-type]
            ),
        )

from __future__ import annotations

from typing import Any
from uuid import UUID

from supabase import Client

from app.core.errors import ApiError


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(format(value, ".12g") for value in vector) + "]"


class SupabaseKnowledgeStore:
    def __init__(self, client: Client) -> None:
        self._client = client

    def get_document(self, document_id: UUID) -> dict[str, Any]:
        response = (
            self._client.table("source_documents").select("*").eq("id", str(document_id)).execute()
        )
        if not response.data:
            raise ApiError(404, "DOCUMENT_NOT_FOUND", "未找到对应的调研资料。")
        return response.data[0]

    def download_file(self, bucket: str, path: str) -> bytes:
        return self._client.storage.from_(bucket).download(path)

    def replace_chunks(self, document_id: UUID, chunks: list[dict[str, Any]]) -> None:
        self._client.table("knowledge_chunks").delete().eq(
            "document_id", str(document_id)
        ).execute()
        if chunks:
            prepared_chunks = [
                {
                    **chunk,
                    "embedding": _vector_literal(chunk["embedding"]),
                }
                for chunk in chunks
            ]
            self._client.table("knowledge_chunks").insert(prepared_chunks).execute()

    def search(
        self,
        project_id: UUID,
        query_embedding: list[float],
        query_text: str,
        limit: int,
        document_kind: str | None,
        product_id: UUID | None,
    ) -> list[dict[str, Any]]:
        response = self._client.rpc(
            "match_knowledge_chunks",
            {
                "p_project_id": str(project_id),
                "p_query_embedding": _vector_literal(query_embedding),
                "p_query_text": query_text,
                "p_match_count": limit,
                "p_document_kind": document_kind,
                "p_product_id": str(product_id) if product_id else None,
            },
        ).execute()
        return response.data or []

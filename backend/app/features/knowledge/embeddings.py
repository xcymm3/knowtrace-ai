from __future__ import annotations

from typing import Protocol

import httpx

from app.core.config import Settings
from app.core.errors import ApiError


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatibleEmbeddingProvider:
    """Minimal adapter for providers implementing POST /embeddings semantics."""

    def __init__(self, settings: Settings) -> None:
        if not settings.embeddings_is_configured:
            raise ApiError(503, "EMBEDDINGS_NOT_CONFIGURED", "Embedding 服务尚未完成配置。")
        if settings.embedding_dimensions != 1536:
            raise ApiError(
                503,
                "EMBEDDING_DIMENSIONS_INVALID",
                "当前数据库索引需要 1536 维 Embedding。",
            )
        self._base_url = (settings.embedding_base_url or "").rstrip("/")
        self._api_key = settings.embedding_api_key or ""
        self._model = settings.embedding_model
        self._dimensions = settings.embedding_dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(
                    f"{self._base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "input": texts},
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as error:
            raise ApiError(
                503, "EMBEDDING_PROVIDER_UNAVAILABLE", "Embedding 服务暂时不可用。"
            ) from error

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or len(data) != len(texts):
            raise ApiError(502, "EMBEDDING_RESPONSE_INVALID", "Embedding 服务返回了无效数据。")

        vectors: list[list[float]] = []
        for item in data:
            vector = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(vector, list) or len(vector) != self._dimensions:
                raise ApiError(502, "EMBEDDING_RESPONSE_INVALID", "Embedding 向量维度不匹配。")
            try:
                vectors.append([float(value) for value in vector])
            except (TypeError, ValueError) as error:
                raise ApiError(
                    502, "EMBEDDING_RESPONSE_INVALID", "Embedding 向量格式无效。"
                ) from error
        return vectors

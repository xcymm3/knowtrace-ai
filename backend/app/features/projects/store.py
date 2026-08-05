from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID

from supabase import Client

from app.core.errors import ApiError


class SupabaseProjectStore:
    def __init__(self, client: Client) -> None:
        self._client = client

    def create_project(self, data: dict[str, Any]) -> dict[str, Any]:
        response = self._client.table("research_projects").insert(data).execute()
        if not response.data:
            raise ApiError(502, "PROJECT_CREATE_FAILED", "调研项目创建失败。")
        return response.data[0]

    def list_projects(self) -> list[dict[str, Any]]:
        response = (
            self._client.table("research_projects")
            .select("*")
            .order("updated_at", desc=True)
            .execute()
        )
        return response.data or []

    def get_project(self, project_id: UUID) -> dict[str, Any]:
        response = (
            self._client.table("research_projects").select("*").eq("id", str(project_id)).execute()
        )
        if not response.data:
            raise ApiError(404, "PROJECT_NOT_FOUND", "未找到对应的调研项目。")
        return response.data[0]

    def update_project(self, project_id: UUID, data: dict[str, Any]) -> dict[str, Any]:
        response = (
            self._client.table("research_projects").update(data).eq("id", str(project_id)).execute()
        )
        if not response.data:
            raise ApiError(404, "PROJECT_NOT_FOUND", "未找到对应的调研项目。")
        return response.data[0]

    def create_product(self, data: dict[str, Any]) -> dict[str, Any]:
        response = self._client.table("products").insert(data).execute()
        if not response.data:
            raise ApiError(502, "PRODUCT_CREATE_FAILED", "商品记录创建失败。")
        return response.data[0]

    def list_products(self, project_id: UUID) -> list[dict[str, Any]]:
        response = (
            self._client.table("products")
            .select("*")
            .eq("project_id", str(project_id))
            .order("created_at")
            .execute()
        )
        return response.data or []

    def get_product(self, project_id: UUID, product_id: UUID) -> dict[str, Any]:
        response = (
            self._client.table("products")
            .select("*")
            .eq("id", str(product_id))
            .eq("project_id", str(project_id))
            .execute()
        )
        if not response.data:
            raise ApiError(404, "PRODUCT_NOT_FOUND", "未找到对应的商品记录。")
        return response.data[0]

    def update_product(
        self, project_id: UUID, product_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        response = (
            self._client.table("products")
            .update(data)
            .eq("id", str(product_id))
            .eq("project_id", str(project_id))
            .execute()
        )
        if not response.data:
            raise ApiError(404, "PRODUCT_NOT_FOUND", "未找到对应的商品记录。")
        return response.data[0]

    def document_coverage(self, project_id: UUID) -> tuple[Counter[str], Counter[str]]:
        response = (
            self._client.table("source_documents")
            .select("product_id,status")
            .eq("project_id", str(project_id))
            .not_.is_("product_id", "null")
            .execute()
        )
        total: Counter[str] = Counter()
        indexed: Counter[str] = Counter()
        for document in response.data or []:
            product_id = document["product_id"]
            total[product_id] += 1
            if document["status"] == "READY":
                indexed[product_id] += 1
        return total, indexed

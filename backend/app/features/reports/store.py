from __future__ import annotations

from typing import Any
from uuid import UUID

from supabase import Client

from app.core.errors import ApiError


class SupabaseReportStore:
    def __init__(self, client: Client) -> None:
        self._client = client

    def get_project(self, project_id: UUID) -> dict[str, Any]:
        response = (
            self._client.table("research_projects").select("*").eq("id", str(project_id)).execute()
        )
        if not response.data:
            raise ApiError(404, "PROJECT_NOT_FOUND", "未找到对应的调研项目。")
        return response.data[0]

    def list_products(self, project_id: UUID) -> list[dict[str, Any]]:
        response = (
            self._client.table("products").select("*").eq("project_id", str(project_id)).execute()
        )
        return response.data or []

    def list_project_evidence(self, project_id: UUID) -> list[dict[str, Any]]:
        documents_response = (
            self._client.table("source_documents")
            .select("id,product_id,file_name,kind,status")
            .eq("project_id", str(project_id))
            .eq("status", "READY")
            .execute()
        )
        documents = documents_response.data or []
        document_ids = [document["id"] for document in documents]
        if not document_ids:
            return []
        chunks_response = (
            self._client.table("knowledge_chunks")
            .select("id,document_id,chunk_index,content")
            .in_("document_id", document_ids)
            .order("chunk_index")
            .execute()
        )
        documents_by_id = {document["id"]: document for document in documents}
        return [
            {**chunk, "document": documents_by_id[chunk["document_id"]]}
            for chunk in (chunks_response.data or [])
            if chunk["document_id"] in documents_by_id
        ]

    def create_report(self, data: dict[str, Any]) -> dict[str, Any]:
        response = self._client.table("selection_reports").insert(data).execute()
        if not response.data:
            raise ApiError(502, "REPORT_CREATE_FAILED", "选品报告创建失败。")
        return response.data[0]

    def create_finding(self, data: dict[str, Any]) -> dict[str, Any]:
        response = self._client.table("report_findings").insert(data).execute()
        if not response.data:
            raise ApiError(502, "FINDING_CREATE_FAILED", "报告结论创建失败。")
        return response.data[0]

    def create_citations(self, data: list[dict[str, Any]]) -> None:
        if data:
            self._client.table("finding_citations").insert(data).execute()

    def get_report(self, project_id: UUID, report_id: UUID) -> dict[str, Any]:
        response = (
            self._client.table("selection_reports")
            .select("*")
            .eq("id", str(report_id))
            .eq("project_id", str(project_id))
            .execute()
        )
        if not response.data:
            raise ApiError(404, "REPORT_NOT_FOUND", "未找到对应的选品报告。")
        return response.data[0]

    def list_reports(self, project_id: UUID) -> list[dict[str, Any]]:
        response = (
            self._client.table("selection_reports")
            .select("*")
            .eq("project_id", str(project_id))
            .order("created_at", desc=True)
            .execute()
        )
        return response.data or []

    def list_findings(self, report_ids: list[str]) -> list[dict[str, Any]]:
        if not report_ids:
            return []
        response = (
            self._client.table("report_findings")
            .select("*")
            .in_("report_id", report_ids)
            .order("position")
            .execute()
        )
        return response.data or []

    def list_citations(self, finding_ids: list[str]) -> list[dict[str, Any]]:
        if not finding_ids:
            return []
        response = (
            self._client.table("finding_citations")
            .select("*")
            .in_("finding_id", finding_ids)
            .order("position")
            .execute()
        )
        return response.data or []

    def chunks_by_id(self, chunk_ids: list[str]) -> list[dict[str, Any]]:
        if not chunk_ids:
            return []
        response = (
            self._client.table("knowledge_chunks")
            .select("id,document_id")
            .in_("id", chunk_ids)
            .execute()
        )
        return response.data or []

    def documents_by_id(self, document_ids: list[str]) -> list[dict[str, Any]]:
        if not document_ids:
            return []
        response = (
            self._client.table("source_documents")
            .select("id,file_name,kind,product_id")
            .in_("id", document_ids)
            .execute()
        )
        return response.data or []

    def create_feedback(self, data: dict[str, Any]) -> dict[str, Any]:
        response = self._client.table("review_feedback").insert(data).execute()
        if not response.data:
            raise ApiError(502, "FEEDBACK_CREATE_FAILED", "审核反馈保存失败。")
        return response.data[0]

    def update_report_status(self, report_id: UUID, status: str) -> None:
        self._client.table("selection_reports").update({"status": status}).eq(
            "id", str(report_id)
        ).execute()

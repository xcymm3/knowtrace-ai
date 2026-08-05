from __future__ import annotations

import asyncio
from collections import defaultdict
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from app.core.errors import ApiError
from app.features.reports.schemas import (
    FindingCitationResponse,
    ReportFindingResponse,
    ReviewDecision,
    ReviewFeedbackCreate,
    ReviewFeedbackResponse,
    SelectionReportCreate,
    SelectionReportResponse,
)


class ReportStore(Protocol):
    def get_project(self, project_id: UUID) -> dict[str, Any]: ...

    def list_products(self, project_id: UUID) -> list[dict[str, Any]]: ...

    def list_project_evidence(self, project_id: UUID) -> list[dict[str, Any]]: ...

    def create_report(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def create_finding(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def create_citations(self, data: list[dict[str, Any]]) -> None: ...

    def get_report(self, project_id: UUID, report_id: UUID) -> dict[str, Any]: ...

    def list_reports(self, project_id: UUID) -> list[dict[str, Any]]: ...

    def list_findings(self, report_ids: list[str]) -> list[dict[str, Any]]: ...

    def list_citations(self, finding_ids: list[str]) -> list[dict[str, Any]]: ...

    def chunks_by_id(self, chunk_ids: list[str]) -> list[dict[str, Any]]: ...

    def documents_by_id(self, document_ids: list[str]) -> list[dict[str, Any]]: ...

    def create_feedback(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def update_report_status(self, report_id: UUID, status: str) -> None: ...


class ReportService:
    def __init__(self, store: ReportStore) -> None:
        self._store = store

    async def create_report(
        self, project_id: UUID, payload: SelectionReportCreate
    ) -> SelectionReportResponse:
        project, products, evidence = await asyncio.gather(
            asyncio.to_thread(self._store.get_project, project_id),
            asyncio.to_thread(self._store.list_products, project_id),
            asyncio.to_thread(self._store.list_project_evidence, project_id),
        )
        selected_products = self._select_products(products, payload.product_ids)
        if not selected_products:
            raise ApiError(422, "REPORT_PRODUCTS_REQUIRED", "请至少录入一个候选商品或竞品。")
        if not evidence:
            raise ApiError(422, "REPORT_EVIDENCE_REQUIRED", "请先上传并完成至少一份资料的索引。")

        evidence_by_product: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
        for item in evidence:
            evidence_by_product[item["document"].get("product_id")].append(item)
        fallback_evidence = evidence_by_product.get(None, []) or evidence
        used_evidence = [
            (product, (evidence_by_product.get(product["id"]) or fallback_evidence)[0])
            for product in selected_products
        ]
        title = payload.title or f"{project['name']}选品对比报告"
        report = await asyncio.to_thread(
            self._store.create_report,
            {
                "project_id": str(project_id),
                "title": title,
                "summary": self._summary(selected_products, evidence),
                "status": "READY_FOR_REVIEW",
                "generation_metadata": {
                    "strategy": "evidence_backed_rules_v1",
                    "productCount": len(selected_products),
                    "evidenceChunkCount": len(evidence),
                },
            },
        )

        position = 1
        for product, source in used_evidence:
            finding = await asyncio.to_thread(
                self._store.create_finding,
                self._product_finding(str(report["id"]), product, position),
            )
            await asyncio.to_thread(
                self._store.create_citations,
                [self._citation(str(finding["id"]), source, 1)],
            )
            position += 1

        comparison_finding = self._price_finding(str(report["id"]), selected_products, position)
        if comparison_finding:
            finding = await asyncio.to_thread(self._store.create_finding, comparison_finding)
            citations = [
                self._citation(str(finding["id"]), source, index + 1)
                for index, (_, source) in enumerate(used_evidence[:2])
            ]
            await asyncio.to_thread(self._store.create_citations, citations)
        return await self.get_report(project_id, UUID(report["id"]))

    async def list_reports(self, project_id: UUID) -> list[SelectionReportResponse]:
        await asyncio.to_thread(self._store.get_project, project_id)
        reports = await asyncio.to_thread(self._store.list_reports, project_id)
        return await self._hydrate_reports(reports)

    async def get_report(self, project_id: UUID, report_id: UUID) -> SelectionReportResponse:
        report = await asyncio.to_thread(self._store.get_report, project_id, report_id)
        return (await self._hydrate_reports([report]))[0]

    async def create_feedback(
        self, project_id: UUID, report_id: UUID, payload: ReviewFeedbackCreate
    ) -> ReviewFeedbackResponse:
        await asyncio.to_thread(self._store.get_report, project_id, report_id)
        if payload.finding_id:
            findings = await asyncio.to_thread(self._store.list_findings, [str(report_id)])
            if str(payload.finding_id) not in {finding["id"] for finding in findings}:
                raise ApiError(422, "FINDING_NOT_IN_REPORT", "审核结论不属于当前报告。")
        record = await asyncio.to_thread(
            self._store.create_feedback,
            {
                "report_id": str(report_id),
                "finding_id": str(payload.finding_id) if payload.finding_id else None,
                "decision": payload.decision.value,
                "comment": payload.comment,
                "reviewer_label": payload.reviewer_label,
            },
        )
        if payload.finding_id is None and payload.decision in {
            ReviewDecision.APPROVED,
            ReviewDecision.REJECTED,
        }:
            await asyncio.to_thread(
                self._store.update_report_status, report_id, payload.decision.value
            )
        return ReviewFeedbackResponse.model_validate(record)

    def _select_products(
        self, products: list[dict[str, Any]], product_ids: list[UUID]
    ) -> list[dict[str, Any]]:
        if not product_ids:
            return products
        requested_ids = {str(product_id) for product_id in product_ids}
        selected = [product for product in products if product["id"] in requested_ids]
        if len(selected) != len(requested_ids):
            raise ApiError(422, "PRODUCT_NOT_IN_PROJECT", "所选商品不属于当前调研项目。")
        return selected

    @staticmethod
    def _summary(products: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> str:
        own_count = sum(product["role"] == "OWN" for product in products)
        competitor_count = sum(product["role"] == "COMPETITOR" for product in products)
        return (
            f"本报告覆盖 {len(products)} 个商品（{own_count} 个自有候选、"
            f"{competitor_count} 个竞品），引用 {len(evidence)} 条已索引资料片段。"
        )

    @staticmethod
    def _product_finding(report_id: str, product: dict[str, Any], position: int) -> dict[str, Any]:
        price = product.get("price")
        price_text = (
            f"当前登记价格为 {price} {product.get('currency') or ''}" if price else "暂未登记价格"
        )
        if product["role"] == "OWN":
            return {
                "report_id": report_id,
                "type": "RECOMMENDATION",
                "title": f"优先验证：{product['name']}",
                "content": (
                    f"{product['name']} 已作为自有候选纳入调研，{price_text}。"
                    "建议围绕引用资料中的参数、评价与需求信号复核其差异化空间。"
                ),
                "confidence": 0.7,
                "position": position,
            }
        return {
            "report_id": report_id,
            "type": "RISK",
            "title": f"竞品基线：{product['name']}",
            "content": (
                f"{product['name']} 已作为竞品参考，{price_text}。"
                "后续审核应结合引用资料确认可替代性、价格带与同质化风险。"
            ),
            "confidence": 0.7,
            "position": position,
        }

    @staticmethod
    def _price_finding(
        report_id: str, products: list[dict[str, Any]], position: int
    ) -> dict[str, Any] | None:
        own_prices = [
            Decimal(str(product["price"]))
            for product in products
            if product["role"] == "OWN" and product.get("price") is not None
        ]
        competitor_prices = [
            Decimal(str(product["price"]))
            for product in products
            if product["role"] == "COMPETITOR" and product.get("price") is not None
        ]
        currencies = {product.get("currency") for product in products if product.get("currency")}
        if not own_prices or not competitor_prices or len(currencies) != 1:
            return None
        own_average = sum(own_prices) / len(own_prices)
        competitor_average = sum(competitor_prices) / len(competitor_prices)
        difference = own_average - competitor_average
        currency = currencies.pop()
        direction = "高于" if difference > 0 else "低于" if difference < 0 else "持平于"
        return {
            "report_id": report_id,
            "type": "DIFFERENTIATOR",
            "title": "价格带对比",
            "content": (
                f"自有候选平均价格为 {own_average:.2f} {currency}，竞品平均价格为 "
                f"{competitor_average:.2f} {currency}；自有候选价格{direction}竞品 "
                f"{abs(difference):.2f} {currency}。"
            ),
            "confidence": 0.8,
            "position": position,
        }

    @staticmethod
    def _citation(finding_id: str, source: dict[str, Any], position: int) -> dict[str, Any]:
        return {
            "finding_id": finding_id,
            "chunk_id": source["id"],
            "excerpt": source["content"].strip()[:800],
            "position": position,
        }

    async def _hydrate_reports(
        self, reports: list[dict[str, Any]]
    ) -> list[SelectionReportResponse]:
        if not reports:
            return []
        findings = await asyncio.to_thread(
            self._store.list_findings, [report["id"] for report in reports]
        )
        citations = await asyncio.to_thread(
            self._store.list_citations, [finding["id"] for finding in findings]
        )
        chunks = await asyncio.to_thread(
            self._store.chunks_by_id, [citation["chunk_id"] for citation in citations]
        )
        documents = await asyncio.to_thread(
            self._store.documents_by_id, [chunk["document_id"] for chunk in chunks]
        )
        chunks_by_id = {chunk["id"]: chunk for chunk in chunks}
        documents_by_id = {document["id"]: document for document in documents}
        citations_by_finding: dict[str, list[FindingCitationResponse]] = defaultdict(list)
        for citation in citations:
            chunk = chunks_by_id.get(citation["chunk_id"])
            document = documents_by_id.get(chunk["document_id"]) if chunk else None
            if not document:
                continue
            citations_by_finding[citation["finding_id"]].append(
                FindingCitationResponse(
                    **citation,
                    document_id=document["id"],
                    file_name=document["file_name"],
                    kind=document["kind"],
                    product_id=document.get("product_id"),
                )
            )
        findings_by_report: dict[str, list[ReportFindingResponse]] = defaultdict(list)
        for finding in findings:
            findings_by_report[finding["report_id"]].append(
                ReportFindingResponse(
                    **finding,
                    citations=citations_by_finding[finding["id"]],
                )
            )
        return [
            SelectionReportResponse(
                **report,
                findings=findings_by_report[report["id"]],
            )
            for report in reports
        ]

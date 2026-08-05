import asyncio
from uuid import UUID, uuid4

from app.features.projects.schemas import ProductRole
from app.features.projects.service import ProjectService
from app.features.reports.schemas import ReviewFeedbackCreate, SelectionReportCreate
from app.features.reports.service import ReportService


def _project(project_id: UUID) -> dict[str, object]:
    return {
        "id": str(project_id),
        "name": "通勤咖啡杯选品",
        "category": "家居",
        "target_platform": "抖音",
        "target_audience": "上班族",
        "status": "ACTIVE",
        "created_at": "2026-08-05T00:00:00+00:00",
        "updated_at": "2026-08-05T00:00:00+00:00",
    }


def _product(product_id: UUID, project_id: UUID, role: str, price: str) -> dict[str, object]:
    return {
        "id": str(product_id),
        "project_id": str(project_id),
        "role": role,
        "name": "自有轻量咖啡杯" if role == "OWN" else "竞品保温咖啡杯",
        "brand_name": "示例品牌",
        "external_url": None,
        "price": price,
        "currency": "CNY",
        "description": "通勤场景使用",
        "attributes": {"capacity": "450ml"},
        "created_at": "2026-08-05T00:00:00+00:00",
        "updated_at": "2026-08-05T00:00:00+00:00",
    }


class FakeProjectStore:
    def __init__(self, project_id: UUID, products: list[dict[str, object]]) -> None:
        self.project = _project(project_id)
        self.products = products

    def get_project(self, _project_id: UUID) -> dict[str, object]:
        return self.project

    def list_products(self, _project_id: UUID) -> list[dict[str, object]]:
        return self.products

    def document_coverage(self, _project_id: UUID) -> tuple[dict[str, int], dict[str, int]]:
        return (
            {str(self.products[0]["id"]): 2, str(self.products[1]["id"]): 1},
            {str(self.products[0]["id"]): 1},
        )


def test_product_comparison_includes_price_and_evidence_coverage() -> None:
    project_id = uuid4()
    products = [
        _product(uuid4(), project_id, "OWN", "59.9"),
        _product(uuid4(), project_id, "COMPETITOR", "49.9"),
    ]
    service = ProjectService(FakeProjectStore(project_id, products))

    result = asyncio.run(service.compare_products(project_id))

    assert result.own_product_count == 1
    assert result.competitor_product_count == 1
    assert result.price_comparisons[0].difference == 10
    assert result.products[0].indexed_document_count == 1
    assert result.products[1].indexed_document_count == 0
    assert result.products[0].product.role is ProductRole.OWN


class FakeReportStore:
    def __init__(self, project_id: UUID, products: list[dict[str, object]]) -> None:
        self.project = _project(project_id)
        self.products = products
        self.report_id = uuid4()
        self.findings: list[dict[str, object]] = []
        self.citations: list[dict[str, object]] = []
        self.feedback: list[dict[str, object]] = []
        self.status_updates: list[str] = []
        self.documents = []
        self.chunks = []
        for product in products:
            document_id = uuid4()
            chunk_id = uuid4()
            self.documents.append(
                {
                    "id": str(document_id),
                    "file_name": f"{product['role']}-资料.xlsx",
                    "kind": "PRODUCT_SHEET",
                    "product_id": product["id"],
                }
            )
            self.chunks.append({"id": str(chunk_id), "document_id": str(document_id)})
        self.evidence = [
            {
                "id": chunk["id"],
                "document_id": chunk["document_id"],
                "chunk_index": 0,
                "content": f"{product['name']} 的容量、材质和通勤评价资料。",
                "document": {
                    **document,
                    "status": "READY",
                },
            }
            for product, document, chunk in zip(products, self.documents, self.chunks, strict=True)
        ]

    def get_project(self, _project_id: UUID) -> dict[str, object]:
        return self.project

    def list_products(self, _project_id: UUID) -> list[dict[str, object]]:
        return self.products

    def list_project_evidence(self, _project_id: UUID) -> list[dict[str, object]]:
        return self.evidence

    def create_report(self, data: dict[str, object]) -> dict[str, object]:
        return {
            "id": str(self.report_id),
            **data,
            "task_id": None,
            "created_at": "2026-08-05T00:00:00+00:00",
            "updated_at": "2026-08-05T00:00:00+00:00",
        }

    def create_finding(self, data: dict[str, object]) -> dict[str, object]:
        finding = {
            "id": str(uuid4()),
            **data,
            "created_at": "2026-08-05T00:00:00+00:00",
            "updated_at": "2026-08-05T00:00:00+00:00",
        }
        self.findings.append(finding)
        return finding

    def create_citations(self, data: list[dict[str, object]]) -> None:
        for citation in data:
            self.citations.append(
                {"id": str(uuid4()), **citation, "created_at": "2026-08-05T00:00:00+00:00"}
            )

    def get_report(self, _project_id: UUID, _report_id: UUID) -> dict[str, object]:
        return self.create_report(
            {
                "project_id": str(_project_id),
                "title": "通勤咖啡杯选品报告",
                "summary": "资料充分",
                "status": "READY_FOR_REVIEW",
                "generation_metadata": {},
            }
        )

    def list_reports(self, _project_id: UUID) -> list[dict[str, object]]:
        return []

    def list_findings(self, _report_ids: list[str]) -> list[dict[str, object]]:
        return self.findings

    def list_citations(self, _finding_ids: list[str]) -> list[dict[str, object]]:
        return self.citations

    def chunks_by_id(self, _chunk_ids: list[str]) -> list[dict[str, object]]:
        return self.chunks

    def documents_by_id(self, _document_ids: list[str]) -> list[dict[str, object]]:
        return self.documents

    def create_feedback(self, data: dict[str, object]) -> dict[str, object]:
        record = {"id": str(uuid4()), **data, "created_at": "2026-08-05T00:00:00+00:00"}
        self.feedback.append(record)
        return record

    def update_report_status(self, _report_id: UUID, status: str) -> None:
        self.status_updates.append(status)


def test_report_is_generated_with_traceable_citations_and_review() -> None:
    project_id = uuid4()
    products = [
        _product(uuid4(), project_id, "OWN", "59.9"),
        _product(uuid4(), project_id, "COMPETITOR", "49.9"),
    ]
    store = FakeReportStore(project_id, products)
    service = ReportService(store)

    report = asyncio.run(service.create_report(project_id, SelectionReportCreate()))
    feedback = asyncio.run(
        service.create_feedback(
            project_id,
            report.id,
            ReviewFeedbackCreate(decision="APPROVED", reviewer_label="类目负责人"),
        )
    )

    assert report.status == "READY_FOR_REVIEW"
    assert len(report.findings) == 3
    assert all(finding.citations for finding in report.findings)
    assert report.findings[-1].title == "价格带对比"
    assert feedback.decision == "APPROVED"
    assert store.status_updates == ["APPROVED"]

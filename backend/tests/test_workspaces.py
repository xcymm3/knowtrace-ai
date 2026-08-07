import asyncio
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import get_workspace_service
from app.features.workspaces.schemas import WorkspaceCreate, WorkspaceUpdate
from app.features.workspaces.service import WorkspaceService
from app.main import app


class FakeWorkspaceStore:
    def __init__(self) -> None:
        self.workspace_id = uuid4()
        self.record: dict[str, object] = {
            "id": str(self.workspace_id),
            "name": "产品研究",
            "description": None,
            "status": "DRAFT",
            "created_at": "2026-08-07T00:00:00Z",
            "updated_at": "2026-08-07T00:00:00Z",
        }

    def create_workspace(self, data: dict[str, object]) -> dict[str, object]:
        self.record = {**self.record, **data}
        return self.record

    def list_workspaces(self) -> list[dict[str, object]]:
        return [self.record]

    def get_workspace(self, _workspace_id: UUID) -> dict[str, object]:
        return self.record

    def update_workspace(self, _workspace_id: UUID, data: dict[str, object]) -> dict[str, object]:
        self.record = {**self.record, **data}
        return self.record


def test_workspace_service_creates_and_updates_generic_workspace() -> None:
    service = WorkspaceService(FakeWorkspaceStore())

    created = asyncio.run(
        service.create_workspace(WorkspaceCreate(name="方案资料", description="MVP"))
    )
    updated = asyncio.run(service.update_workspace(created.id, WorkspaceUpdate(status="ACTIVE")))

    assert created.name == "方案资料"
    assert created.description == "MVP"
    assert updated.status == "ACTIVE"


def test_workspace_api_uses_workspace_routes() -> None:
    service = WorkspaceService(FakeWorkspaceStore())
    app.dependency_overrides[get_workspace_service] = lambda: service
    client = TestClient(app)

    try:
        create_response = client.post("/api/v1/workspaces", json={"name": "会议资料"})
        list_response = client.get("/api/v1/workspaces")
    finally:
        app.dependency_overrides.clear()

    assert create_response.status_code == 201
    assert list_response.status_code == 200
    assert list_response.json()[0]["name"] == "会议资料"

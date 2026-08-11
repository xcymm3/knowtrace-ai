from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import get_task_control_service, get_task_store
from app.main import app


class FakeTaskStore:
    def __init__(self, task_id: str, workspace_id: str) -> None:
        self._task = {
            "id": task_id,
            "workspace_id": workspace_id,
            "document_id": None,
            "task_type": "PARSE_DOCUMENT",
            "status": "SUCCEEDED",
            "progress": 100,
            "attempt_count": 1,
            "max_attempts": 3,
            "output_payload": {"parser": "csv"},
            "error_message": None,
            "started_at": None,
            "completed_at": None,
        }

    def get_task(self, _task_id: object) -> dict[str, object]:
        return self._task

    def list_workspace_tasks(self, _workspace_id: object) -> list[dict[str, object]]:
        return [self._task]


class FakeTaskControlService:
    async def retry_task(self, _workspace_id: object, _task_id: object) -> dict[str, object]:
        return {
            "id": str(uuid4()),
            "workspace_id": str(uuid4()),
            "document_id": None,
            "task_type": "PARSE_DOCUMENT",
            "status": "QUEUED",
            "progress": 0,
            "attempt_count": 0,
            "max_attempts": 3,
            "output_payload": {},
            "error_message": None,
            "started_at": None,
            "completed_at": None,
        }

    async def cancel_task(self, _workspace_id: object, _task_id: object) -> dict[str, object]:
        return {
            "id": str(uuid4()),
            "workspace_id": str(uuid4()),
            "document_id": None,
            "task_type": "PARSE_DOCUMENT",
            "status": "CANCELLED",
            "progress": 10,
            "attempt_count": 1,
            "max_attempts": 3,
            "output_payload": {},
            "error_message": "已由用户取消。",
            "started_at": None,
            "completed_at": None,
        }


def test_task_status_and_sse_completion_event() -> None:
    task_id = uuid4()
    workspace_id = uuid4()
    app.dependency_overrides[get_task_store] = lambda: FakeTaskStore(
        str(task_id), str(workspace_id)
    )
    client = TestClient(app)

    try:
        status_response = client.get(f"/api/v1/tasks/{task_id}")
        stream_response = client.get(f"/api/v1/tasks/{task_id}/events")
    finally:
        app.dependency_overrides.clear()

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "SUCCEEDED"
    assert stream_response.status_code == 200
    assert "event: progress" in stream_response.text
    assert "event: complete" in stream_response.text


def test_list_project_tasks() -> None:
    task_id = uuid4()
    workspace_id = uuid4()
    app.dependency_overrides[get_task_store] = lambda: FakeTaskStore(
        str(task_id), str(workspace_id)
    )
    client = TestClient(app)

    try:
        response = client.get(f"/api/v1/tasks/workspaces/{workspace_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["id"] == str(task_id)


def test_retry_and_cancel_task_routes_return_updated_task_state() -> None:
    task_id = uuid4()
    workspace_id = uuid4()
    app.dependency_overrides[get_task_store] = lambda: FakeTaskStore(
        str(task_id), str(workspace_id)
    )
    app.dependency_overrides[get_task_control_service] = lambda: FakeTaskControlService()
    client = TestClient(app)

    try:
        retry_response = client.post(f"/api/v1/tasks/{task_id}/retry")
        cancel_response = client.post(f"/api/v1/tasks/{task_id}/cancel")
    finally:
        app.dependency_overrides.clear()

    assert retry_response.status_code == 200
    assert retry_response.json()["status"] == "QUEUED"
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "CANCELLED"

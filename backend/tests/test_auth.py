from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.main import app


def test_workspace_api_rejects_anonymous_requests() -> None:
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app)

    response = client.get("/api/v1/workspaces")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

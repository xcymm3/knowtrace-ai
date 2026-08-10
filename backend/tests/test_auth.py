from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.api.dependencies import get_username_sign_in_service
from app.features.authentication.schemas import UsernameAvailabilityResponse, UsernameSignInResponse
from app.main import app


def test_workspace_api_rejects_anonymous_requests() -> None:
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app)

    response = client.get("/api/v1/workspaces")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_username_sign_in_returns_supabase_session() -> None:
    class FakeUsernameSignInService:
        async def sign_in(self, payload: object) -> UsernameSignInResponse:
            assert getattr(payload, "identity") == "knowtrace"
            assert getattr(payload, "password") == "weak-password"
            return UsernameSignInResponse(
                access_token="access-token",
                refresh_token="refresh-token",
                expires_in=3600,
                token_type="bearer",
            )

    app.dependency_overrides[get_username_sign_in_service] = FakeUsernameSignInService
    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/sign-in",
        json={"identity": "knowtrace", "password": "weak-password"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "access-token"
    assert response.json()["refresh_token"] == "refresh-token"


def test_username_availability_returns_explicit_status() -> None:
    class FakeUsernameSignInService:
        def username_availability(self, username: str) -> UsernameAvailabilityResponse:
            assert username == "knowtrace"
            return UsernameAvailabilityResponse(available=False)

    app.dependency_overrides[get_username_sign_in_service] = FakeUsernameSignInService
    client = TestClient(app)

    response = client.get("/api/v1/auth/username-availability", params={"username": "knowtrace"})

    assert response.status_code == 200
    assert response.json() == {"available": False}

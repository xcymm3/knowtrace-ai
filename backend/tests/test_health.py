from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

client = TestClient(app)


def setup_function() -> None:
    get_settings.cache_clear()


def test_health_returns_liveness_payload() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "KnowTrace API",
        "environment": "development",
    }


def test_readiness_is_degraded_without_supabase_configuration(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setenv("REDIS_URL", "")
    get_settings.cache_clear()

    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "components": {
            "api": "ready",
            "supabase": "not_configured",
            "redis": "not_configured",
        },
    }


def test_openapi_exposes_health_contract() -> None:
    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]

from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.core.config import Settings, get_settings

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    environment: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    components: dict[str, Literal["ready", "not_configured"]]


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def get_health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Confirm the API process is running without touching external services."""
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.app_environment,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    summary="Configuration readiness probe",
)
async def get_readiness(settings: Settings = Depends(get_settings)) -> ReadinessResponse:
    """Report configuration state without exposing connection strings or keys."""
    supabase_is_ready = settings.supabase_is_configured
    redis_is_ready = settings.redis_is_configured

    return ReadinessResponse(
        status="ready" if supabase_is_ready and redis_is_ready else "degraded",
        components={
            "api": "ready",
            "supabase": "ready" if supabase_is_ready else "not_configured",
            "redis": "ready" if redis_is_ready else "not_configured",
        },
    )

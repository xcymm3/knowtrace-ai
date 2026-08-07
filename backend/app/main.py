from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers

settings = get_settings()

app = FastAPI(
    title="KnowTrace API",
    summary="Evidence-backed APIs for traceable knowledge workspaces.",
    description=(
        "The domain API for KnowTrace AI. It will manage workspaces, documents, "
        "background tasks and traceable retrieval results."
    ),
    version="0.1.0",
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Request-ID"],
)
register_error_handlers(app)

app.include_router(api_router, prefix=settings.api_v1_prefix)


class RootResponse(BaseModel):
    service: str
    version: str
    docs_url: str


@app.get("/", response_model=RootResponse, tags=["system"], summary="Service identity")
async def get_root() -> RootResponse:
    return RootResponse(
        service=settings.app_name,
        version=app.version,
        docs_url="/docs",
    )

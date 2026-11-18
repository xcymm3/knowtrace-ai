import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel

from app.api.v1.agent import get_agent_runs
from app.api.v1.health import router as health_router
from app.api.v1.local_agent import router as local_agent_router
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.features.agent.local import serve_local
from app.features.agent.local_store import LocalRunStore

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.local_agent_root is None:
        yield
        return
    runs = get_agent_runs()
    if not isinstance(runs.store, LocalRunStore):
        yield
        return
    with runs.store.exclusive_worker():
        await asyncio.to_thread(runs.store.interrupt_active)
        worker = asyncio.create_task(serve_local(settings, runs))
        try:
            yield
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


app = FastAPI(
    title="KnowTrace API",
    summary="KnowTrace local Agent API.",
    version="0.1.0",
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

if settings.local_agent_root is not None:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Request-ID"],
)
register_error_handlers(app)

if settings.local_agent_root is not None:
    app.include_router(health_router, prefix=settings.api_v1_prefix)
    app.include_router(local_agent_router, prefix=settings.api_v1_prefix)
else:
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

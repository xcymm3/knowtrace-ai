from fastapi import APIRouter

from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.projects import router as projects_router
from app.api.v1.reports import router as reports_router
from app.api.v1.tasks import router as tasks_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(documents_router)
api_router.include_router(tasks_router)
api_router.include_router(knowledge_router)
api_router.include_router(projects_router)
api_router.include_router(reports_router)

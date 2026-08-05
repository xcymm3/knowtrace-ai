from functools import lru_cache

from app.core.config import get_settings
from app.features.documents.service import DocumentIngestionService
from app.features.documents.store import SupabaseDocumentStore, create_supabase_client
from app.features.knowledge.embeddings import OpenAICompatibleEmbeddingProvider
from app.features.knowledge.service import KnowledgeSearchService
from app.features.knowledge.store import SupabaseKnowledgeStore
from app.features.projects.service import ProjectService
from app.features.projects.store import SupabaseProjectStore
from app.features.reports.service import ReportService
from app.features.reports.store import SupabaseReportStore
from app.features.tasks.queue import ArqTaskQueue
from app.features.tasks.store import SupabaseTaskStore


@lru_cache
def get_document_ingestion_service() -> DocumentIngestionService:
    settings = get_settings()
    client = create_supabase_client(settings)
    return DocumentIngestionService(
        store=SupabaseDocumentStore(client, settings.supabase_storage_bucket),
        queue=ArqTaskQueue(settings.redis_url),
        settings=settings,
    )


@lru_cache
def get_task_store() -> SupabaseTaskStore:
    settings = get_settings()
    return SupabaseTaskStore(
        create_supabase_client(settings),
        settings.supabase_storage_bucket,
    )


@lru_cache
def get_knowledge_search_service() -> KnowledgeSearchService:
    settings = get_settings()
    return KnowledgeSearchService(
        store=SupabaseKnowledgeStore(create_supabase_client(settings)),
        embeddings=OpenAICompatibleEmbeddingProvider(settings),
    )


@lru_cache
def get_project_service() -> ProjectService:
    settings = get_settings()
    return ProjectService(store=SupabaseProjectStore(create_supabase_client(settings)))


@lru_cache
def get_report_service() -> ReportService:
    settings = get_settings()
    return ReportService(store=SupabaseReportStore(create_supabase_client(settings)))

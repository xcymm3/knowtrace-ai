from functools import lru_cache

from app.core.config import get_settings
from app.features.conversations.service import RagConversationService
from app.features.conversations.store import SupabaseConversationStore
from app.features.documents.service import DocumentIngestionService
from app.features.documents.store import SupabaseDocumentStore, create_supabase_client
from app.features.knowledge.embeddings import OpenAICompatibleEmbeddingProvider
from app.features.knowledge.service import KnowledgeSearchService
from app.features.knowledge.store import SupabaseKnowledgeStore
from app.features.llm.service import LangChainAnswerService, build_langchain_answer_service
from app.features.tasks.queue import ArqTaskQueue
from app.features.tasks.store import SupabaseTaskStore
from app.features.workspaces.service import WorkspaceService
from app.features.workspaces.store import SupabaseWorkspaceStore


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
def get_langchain_answer_service() -> LangChainAnswerService:
    return build_langchain_answer_service(get_settings())


@lru_cache
def get_rag_conversation_service() -> RagConversationService:
    settings = get_settings()
    return RagConversationService(
        store=SupabaseConversationStore(create_supabase_client(settings)),
        retrieval=get_knowledge_search_service(),
        answers=get_langchain_answer_service(),
    )


@lru_cache
def get_workspace_service() -> WorkspaceService:
    settings = get_settings()
    return WorkspaceService(store=SupabaseWorkspaceStore(create_supabase_client(settings)))

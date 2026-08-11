from __future__ import annotations

from uuid import UUID

import anyio

from app.core.config import Settings
from app.features.documents.store import create_supabase_client
from app.features.knowledge.embeddings import OpenAICompatibleEmbeddingProvider
from app.features.knowledge.store import SupabaseKnowledgeStore
from app.features.tasks.store import SupabaseTaskStore
from app.features.tasks.worker import process_generate_embeddings, process_parse_document


class InlineTaskQueue:
    """Run short ingestion jobs inside a serverless API request.

    Vercel can serve FastAPI requests but cannot keep the ARQ worker alive.
    This adapter deliberately shares the task records and worker functions, so
    Docker continues to use Redis while serverless deployments still complete
    parsing and indexing instead of leaving durable jobs unconsumed.
    """

    def __init__(self, settings: Settings) -> None:
        client = create_supabase_client(settings)
        self._settings = settings
        self._task_store = SupabaseTaskStore(client, settings.supabase_storage_bucket)
        self._knowledge_store = SupabaseKnowledgeStore(client)

    async def enqueue_parse_document(self, task_id: UUID) -> None:
        async def enqueue_embedding(embedding_task_id: UUID) -> None:
            await self.enqueue_generate_embeddings(embedding_task_id)

        await process_parse_document(
            self._task_store,
            task_id,
            attempt=1,
            max_extracted_characters=self._settings.document_max_extracted_characters,
            enqueue_embedding=enqueue_embedding,
        )

    async def enqueue_generate_embeddings(self, task_id: UUID) -> None:
        await process_generate_embeddings(
            self._task_store,
            self._knowledge_store,
            OpenAICompatibleEmbeddingProvider(self._settings),
            task_id,
            attempt=1,
            embedding_model=self._settings.embedding_model,
        )

    async def resume_workspace_tasks(self, workspace_id: UUID) -> None:
        """Recover one unfinished task left by an earlier serverless request."""
        tasks = await anyio.to_thread.run_sync(self._task_store.list_workspace_tasks, workspace_id)
        for task in tasks:
            if task["status"] not in {"QUEUED", "RUNNING"}:
                continue
            task_id = UUID(str(task["id"]))
            if task["task_type"] == "PARSE_DOCUMENT":
                await self.enqueue_parse_document(task_id)
                return
            if task["task_type"] == "GENERATE_EMBEDDINGS":
                await self.enqueue_generate_embeddings(task_id)
                return

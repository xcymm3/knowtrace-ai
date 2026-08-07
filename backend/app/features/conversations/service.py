from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.core.errors import ApiError
from app.features.conversations.schemas import (
    ConversationCreate,
    ConversationMessageResponse,
    ConversationResponse,
    MessageResponse,
    RagQuestionRequest,
    RagSource,
)
from app.features.knowledge.schemas import KnowledgeSearchRequest, KnowledgeSearchResponse
from app.features.llm.schemas import GroundedAnswerRequest


class ConversationStore(Protocol):
    def workspace_exists(self, workspace_id: UUID) -> bool: ...
    def create_conversation(self, data: dict[str, Any]) -> dict[str, Any]: ...
    def list_conversations(self, workspace_id: UUID) -> list[dict[str, Any]]: ...
    def get_conversation(self, workspace_id: UUID, conversation_id: UUID) -> dict[str, Any]: ...
    def next_sequence(self, conversation_id: UUID) -> int: ...
    def list_messages(self, conversation_id: UUID) -> list[dict[str, Any]]: ...
    def list_citations(self, message_ids: list[UUID]) -> list[dict[str, Any]]: ...
    def get_chunks(self, chunk_ids: list[UUID]) -> list[dict[str, Any]]: ...
    def get_documents(self, document_ids: list[UUID]) -> list[dict[str, Any]]: ...
    def create_message(self, data: dict[str, Any]) -> dict[str, Any]: ...
    def touch_conversation(self, conversation_id: UUID) -> None: ...
    def create_citations(self, rows: list[dict[str, Any]]) -> None: ...


class RetrievalService(Protocol):
    async def search(
        self, workspace_id: UUID, request: KnowledgeSearchRequest
    ) -> KnowledgeSearchResponse: ...


class AnswerService(Protocol):
    async def stream(self, request: GroundedAnswerRequest) -> AsyncIterator[str]: ...


@dataclass(frozen=True)
class PreparedRagTurn:
    workspace_id: UUID
    conversation_id: UUID
    user_message: MessageResponse
    question: str
    sources: list[RagSource]
    context: str


class RagConversationService:
    def __init__(
        self,
        store: ConversationStore,
        retrieval: RetrievalService,
        answers: AnswerService,
    ) -> None:
        self._store = store
        self._retrieval = retrieval
        self._answers = answers

    async def create_conversation(
        self, workspace_id: UUID, payload: ConversationCreate
    ) -> ConversationResponse:
        exists = await asyncio.to_thread(self._store.workspace_exists, workspace_id)
        if not exists:
            raise ApiError(404, "WORKSPACE_NOT_FOUND", "未找到对应的工作区。")
        record = await asyncio.to_thread(
            self._store.create_conversation,
            {"workspace_id": str(workspace_id), **payload.model_dump()},
        )
        return ConversationResponse.model_validate(record)

    async def list_conversations(self, workspace_id: UUID) -> list[ConversationResponse]:
        exists = await asyncio.to_thread(self._store.workspace_exists, workspace_id)
        if not exists:
            raise ApiError(404, "WORKSPACE_NOT_FOUND", "未找到对应的工作区。")
        records = await asyncio.to_thread(self._store.list_conversations, workspace_id)
        return [ConversationResponse.model_validate(record) for record in records]

    async def list_messages(
        self, workspace_id: UUID, conversation_id: UUID
    ) -> list[ConversationMessageResponse]:
        await asyncio.to_thread(self._store.get_conversation, workspace_id, conversation_id)
        records = await asyncio.to_thread(self._store.list_messages, conversation_id)
        messages = [MessageResponse.model_validate(record) for record in records]
        citations = await asyncio.to_thread(
            self._store.list_citations, [message.id for message in messages]
        )
        chunk_ids = [UUID(str(citation["chunk_id"])) for citation in citations]
        chunks = await asyncio.to_thread(self._store.get_chunks, chunk_ids)
        chunk_by_id = {str(chunk["id"]): chunk for chunk in chunks}
        document_ids = [UUID(str(chunk["document_id"])) for chunk in chunks]
        documents = await asyncio.to_thread(self._store.get_documents, document_ids)
        document_by_id = {str(document["id"]): document for document in documents}
        sources_by_message: dict[str, list[RagSource]] = {}

        for citation in citations:
            chunk = chunk_by_id.get(str(citation["chunk_id"]))
            if not chunk:
                continue
            document = document_by_id.get(str(chunk["document_id"]))
            if not document:
                continue
            metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            sources_by_message.setdefault(str(citation["message_id"]), []).append(
                RagSource(
                    chunk_id=UUID(str(citation["chunk_id"])),
                    citation={
                        "document_id": UUID(str(document["id"])),
                        "file_name": str(document["file_name"]),
                        "kind": document["kind"],
                        "chunk_index": int(metadata.get("chunkIndex", 0)),
                        "start_char": metadata.get("startChar"),
                        "end_char": metadata.get("endChar"),
                    },
                    excerpt=str(citation["excerpt"]),
                )
            )

        return [
            ConversationMessageResponse(
                **message.model_dump(), sources=sources_by_message.get(str(message.id), [])
            )
            for message in messages
        ]

    async def prepare_turn(
        self,
        workspace_id: UUID,
        conversation_id: UUID,
        request: RagQuestionRequest,
    ) -> PreparedRagTurn:
        await asyncio.to_thread(self._store.get_conversation, workspace_id, conversation_id)
        retrieval = await self._retrieval.search(
            workspace_id,
            KnowledgeSearchRequest(query=request.question, limit=request.retrieval_limit),
        )
        if not retrieval.hits:
            raise ApiError(422, "KNOWLEDGE_EMPTY", "当前工作区还没有可用于回答的已索引资料。")

        sequence = await asyncio.to_thread(self._store.next_sequence, conversation_id)
        user_record = await asyncio.to_thread(
            self._store.create_message,
            {
                "id": str(uuid4()),
                "conversation_id": str(conversation_id),
                "role": "USER",
                "content": request.question,
                "sequence": sequence,
            },
        )
        sources = [
            RagSource(
                chunk_id=hit.chunk_id,
                citation=hit.citation,
                excerpt=hit.content[:1200],
                score=hit.final_score,
            )
            for hit in retrieval.hits
        ]
        return PreparedRagTurn(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            user_message=MessageResponse.model_validate(user_record),
            question=request.question,
            sources=sources,
            context=self._format_context(sources),
        )

    async def stream_turn(self, turn: PreparedRagTurn) -> AsyncIterator[dict[str, object]]:
        yield {
            "event": "retrieval",
            "data": {
                "conversation_id": str(turn.conversation_id),
                "sources": [source.model_dump(mode="json") for source in turn.sources],
            },
        }
        parts: list[str] = []
        async for delta in self._answers.stream(
            GroundedAnswerRequest(question=turn.question, context=turn.context)
        ):
            parts.append(delta)
            yield {"event": "token", "data": {"delta": delta}}

        content = "".join(parts).strip()
        if not content:
            raise ApiError(502, "LLM_EMPTY_RESPONSE", "模型没有返回可用回答。")
        message_id = uuid4()
        record = await asyncio.to_thread(
            self._store.create_message,
            {
                "id": str(message_id),
                "conversation_id": str(turn.conversation_id),
                "role": "ASSISTANT",
                "content": content,
                "sequence": turn.user_message.sequence + 1,
                "retrieval_metadata": {
                    "query": turn.question,
                    "sourceChunkIds": [str(source.chunk_id) for source in turn.sources],
                },
            },
        )
        await asyncio.to_thread(
            self._store.create_citations,
            [
                {
                    "id": str(uuid4()),
                    "message_id": str(message_id),
                    "chunk_id": str(source.chunk_id),
                    "excerpt": source.excerpt,
                    "citation_order": index,
                }
                for index, source in enumerate(turn.sources, start=1)
            ],
        )
        await asyncio.to_thread(self._store.touch_conversation, turn.conversation_id)
        yield {
            "event": "complete",
            "data": {
                "message": MessageResponse.model_validate(record).model_dump(mode="json"),
                "sources": [source.model_dump(mode="json") for source in turn.sources],
            },
        }

    @staticmethod
    def _format_context(sources: list[RagSource]) -> str:
        return "\n\n".join(
            (
                f"[来源 {index}] {source.citation.file_name}，"
                f"片段 {source.citation.chunk_index}\n{source.excerpt}"
            )
            for index, source in enumerate(sources, start=1)
        )

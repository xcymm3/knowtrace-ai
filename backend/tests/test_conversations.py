import asyncio
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import get_rag_conversation_service
from app.features.conversations.schemas import ConversationCreate, RagQuestionRequest
from app.features.conversations.service import RagConversationService
from app.features.knowledge.schemas import (
    KnowledgeCitation,
    KnowledgeSearchHit,
    KnowledgeSearchResponse,
)
from app.main import app


class FakeConversationStore:
    def __init__(self) -> None:
        self.workspace_id = uuid4()
        self.conversation_id = uuid4()
        self.messages: list[dict[str, object]] = []
        self.citations: list[dict[str, object]] = []
        self.touched = False
        self.conversation = {
            "id": str(self.conversation_id),
            "workspace_id": str(self.workspace_id),
            "title": "新对话",
            "created_at": "2026-08-07T00:00:00Z",
            "updated_at": "2026-08-07T00:00:00Z",
        }

    def workspace_exists(self, workspace_id: UUID) -> bool:
        return workspace_id == self.workspace_id

    def create_conversation(self, data: dict[str, object]) -> dict[str, object]:
        self.conversation = {**self.conversation, **data}
        return self.conversation

    def list_conversations(self, _workspace_id: UUID) -> list[dict[str, object]]:
        return [self.conversation]

    def get_conversation(self, workspace_id: UUID, conversation_id: UUID) -> dict[str, object]:
        assert workspace_id == self.workspace_id
        assert conversation_id == self.conversation_id
        return self.conversation

    def next_sequence(self, _conversation_id: UUID) -> int:
        return len(self.messages)

    def list_messages(self, _conversation_id: UUID) -> list[dict[str, object]]:
        return self.messages

    def list_citations(self, _message_ids: list[UUID]) -> list[dict[str, object]]:
        return self.citations

    def get_chunks(self, _chunk_ids: list[UUID]) -> list[dict[str, object]]:
        return []

    def get_documents(self, _document_ids: list[UUID]) -> list[dict[str, object]]:
        return []

    def create_message(self, data: dict[str, object]) -> dict[str, object]:
        record = {**data, "created_at": "2026-08-07T00:00:01Z"}
        self.messages.append(record)
        return record

    def create_citations(self, rows: list[dict[str, object]]) -> None:
        self.citations.extend(rows)

    def touch_conversation(self, _conversation_id: UUID) -> None:
        self.touched = True


class FakeRetrieval:
    async def search(self, workspace_id: UUID, request: object) -> KnowledgeSearchResponse:
        assert workspace_id
        assert request
        chunk_id = uuid4()
        document_id = uuid4()
        return KnowledgeSearchResponse(
            workspace_id=workspace_id,
            query="会议结论是什么？",
            hits=[
                KnowledgeSearchHit(
                    chunk_id=chunk_id,
                    content="会议决定继续推进，并由张三负责下周的验证。",
                    semantic_score=0.91,
                    keyword_score=0.6,
                    final_score=0.83,
                    citation=KnowledgeCitation(
                        document_id=document_id,
                        file_name="会议纪要.docx",
                        kind="NOTE",
                        chunk_index=0,
                        start_char=0,
                        end_char=23,
                    ),
                )
            ],
        )


class FakeAnswers:
    async def stream(self, _request: object) -> AsyncIterator[str]:
        yield "根据会议纪要，"
        yield "项目将继续推进。"


def create_service() -> tuple[RagConversationService, FakeConversationStore]:
    store = FakeConversationStore()
    return RagConversationService(store, FakeRetrieval(), FakeAnswers()), store


def test_rag_turn_streams_and_persists_traceable_citations() -> None:
    service, store = create_service()
    turn = asyncio.run(
        service.prepare_turn(
            store.workspace_id,
            store.conversation_id,
            RagQuestionRequest(question="会议结论是什么？"),
        )
    )

    async def collect() -> list[dict[str, object]]:
        return [event async for event in service.stream_turn(turn)]

    events = asyncio.run(collect())

    assert [event["event"] for event in events] == ["retrieval", "token", "token", "complete"]
    assert store.messages[0]["role"] == "USER"
    assert store.messages[1]["role"] == "ASSISTANT"
    assert store.citations[0]["chunk_id"] == str(turn.sources[0].chunk_id)
    assert store.touched is True


def test_rag_stream_api_emits_retrieval_tokens_and_completion() -> None:
    service, store = create_service()
    app.dependency_overrides[get_rag_conversation_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            f"/api/v1/workspaces/{store.workspace_id}/conversations/{store.conversation_id}/messages/stream",
            json={"question": "会议结论是什么？"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "event: retrieval" in response.text
    assert "event: token" in response.text
    assert "event: complete" in response.text


def test_conversation_create_api_uses_workspace_scope() -> None:
    service, store = create_service()
    app.dependency_overrides[get_rag_conversation_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            f"/api/v1/workspaces/{store.workspace_id}/conversations",
            json=ConversationCreate(title="会议问答").model_dump(),
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["title"] == "会议问答"


def test_conversation_messages_api_returns_saved_history() -> None:
    service, store = create_service()
    asyncio.run(
        service.prepare_turn(
            store.workspace_id,
            store.conversation_id,
            RagQuestionRequest(question="会议结论是什么？"),
        )
    )
    app.dependency_overrides[get_rag_conversation_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.get(
            f"/api/v1/workspaces/{store.workspace_id}/conversations/{store.conversation_id}/messages"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["role"] == "USER"

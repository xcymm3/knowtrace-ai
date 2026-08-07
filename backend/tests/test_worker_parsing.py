import asyncio
from uuid import UUID, uuid4

import pytest
from arq import Retry

from app.features.tasks.worker import process_generate_embeddings, process_parse_document


class FakeParseStore:
    def __init__(self, content: bytes, *, download_error: Exception | None = None) -> None:
        self.workspace_id = uuid4()
        self.document_id = uuid4()
        self.task_id = uuid4()
        self.content = content
        self.download_error = download_error
        self.task: dict[str, object] = {
            "id": str(self.task_id),
            "document_id": str(self.document_id),
            "status": "QUEUED",
            "progress": 0,
            "attempt_count": 0,
            "max_attempts": 3,
        }
        self.document: dict[str, object] = {
            "id": str(self.document_id),
            "workspace_id": str(self.workspace_id),
            "storage_path": "source/notes.md",
            "mime_type": "text/markdown",
            "file_name": "notes.md",
            "metadata": {},
            "status": "PENDING",
        }
        self.derived: dict[str, bytes] = {}
        self.created_embedding_tasks: list[dict[str, object]] = []

    def get_task(self, _task_id: UUID) -> dict[str, object]:
        return self.task

    def update_task(self, _task_id: UUID, data: dict[str, object]) -> None:
        self.task.update(data)

    def get_document(self, _document_id: UUID) -> dict[str, object]:
        return self.document

    def update_document(self, _document_id: UUID, data: dict[str, object]) -> None:
        self.document.update(data)

    def download_file(self, _path: str) -> bytes:
        if self.download_error:
            raise self.download_error
        return self.content

    def upload_derived_text(self, path: str, content: bytes) -> None:
        self.derived[path] = content

    def create_embedding_task(self, data: dict[str, object]) -> dict[str, object]:
        self.created_embedding_tasks.append(data)
        return data


def test_parse_worker_writes_derived_text_and_marks_document_parsed() -> None:
    store = FakeParseStore("# 结论\n\n继续推进。".encode())

    asyncio.run(
        process_parse_document(store, store.task_id, attempt=1, max_extracted_characters=100)
    )

    assert store.task["status"] == "SUCCEEDED"
    assert store.task["output_payload"] == {
        "parser": "text",
        "characterCount": 11,
        "needsOcr": False,
        "indexStatus": "PENDING",
        "embeddingTaskId": None,
    }
    assert store.document["status"] == "PARSED"
    assert store.document["metadata"]["parse"]["hasExtractedText"] is True
    assert next(iter(store.derived.values())).decode() == "# 结论\n\n继续推进。"


def test_parse_worker_creates_and_enqueues_embedding_task() -> None:
    store = FakeParseStore("可检索的知识资料。".encode())
    queued: list[UUID] = []

    async def enqueue(task_id: UUID) -> None:
        queued.append(task_id)

    asyncio.run(
        process_parse_document(
            store,
            store.task_id,
            attempt=1,
            max_extracted_characters=100,
            enqueue_embedding=enqueue,
        )
    )

    assert store.document["status"] == "PROCESSING"
    assert store.task["output_payload"]["indexStatus"] == "QUEUED"
    assert len(store.created_embedding_tasks) == 1
    assert queued == [UUID(str(store.created_embedding_tasks[0]["id"]))]


def test_parse_worker_requeues_transient_failures() -> None:
    store = FakeParseStore(b"", download_error=RuntimeError("storage timeout"))

    with pytest.raises(Retry):
        asyncio.run(
            process_parse_document(store, store.task_id, attempt=1, max_extracted_characters=100)
        )

    assert store.task["status"] == "QUEUED"
    assert store.task["attempt_count"] == 1
    assert store.document["status"] == "PENDING"


class FakeIndexStore:
    def __init__(self) -> None:
        self.workspace_id = uuid4()
        self.document_id = uuid4()
        self.task_id = uuid4()
        self.task: dict[str, object] = {
            "id": str(self.task_id),
            "document_id": str(self.document_id),
            "status": "QUEUED",
            "progress": 0,
            "attempt_count": 0,
            "max_attempts": 3,
        }
        self.document: dict[str, object] = {
            "id": str(self.document_id),
            "workspace_id": str(self.workspace_id),
            "storage_bucket": "knowtrace-assets",
            "metadata": {"extractedTextPath": "derived/extracted.txt"},
            "status": "PARSED",
        }
        self.chunks: list[dict[str, object]] = []

    def get_task(self, _task_id: UUID) -> dict[str, object]:
        return self.task

    def update_task(self, _task_id: UUID, data: dict[str, object]) -> None:
        self.task.update(data)

    def update_document(self, _document_id: UUID, data: dict[str, object]) -> None:
        self.document.update(data)

    def get_document(self, _document_id: UUID) -> dict[str, object]:
        return self.document

    def download_file(self, _bucket: str, _path: str) -> bytes:
        return "第一段资料。\n\n第二段资料。".encode()

    def replace_chunks(self, _document_id: UUID, chunks: list[dict[str, object]]) -> None:
        self.chunks = chunks


class FakeEmbeddings:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2] for _ in texts]


def test_embedding_worker_indexes_chunks_and_marks_document_ready() -> None:
    store = FakeIndexStore()

    asyncio.run(
        process_generate_embeddings(
            store,
            store,
            FakeEmbeddings(),
            store.task_id,
            attempt=1,
            embedding_model="test-embedding",
        )
    )

    assert store.task["status"] == "SUCCEEDED"
    assert store.document["status"] == "READY"
    assert store.document["metadata"]["index"]["chunkCount"] == len(store.chunks)
    assert store.chunks[0]["workspace_id"] == str(store.workspace_id)

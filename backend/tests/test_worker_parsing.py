import asyncio
from uuid import UUID, uuid4

import pytest
from arq import Retry

from app.features.tasks.worker import process_parse_document


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
    }
    assert store.document["status"] == "PARSED"
    assert store.document["metadata"]["parse"]["hasExtractedText"] is True
    assert next(iter(store.derived.values())).decode() == "# 结论\n\n继续推进。"


def test_parse_worker_requeues_transient_failures() -> None:
    store = FakeParseStore(b"", download_error=RuntimeError("storage timeout"))

    with pytest.raises(Retry):
        asyncio.run(
            process_parse_document(store, store.task_id, attempt=1, max_extracted_characters=100)
        )

    assert store.task["status"] == "QUEUED"
    assert store.task["attempt_count"] == 1
    assert store.document["status"] == "PENDING"

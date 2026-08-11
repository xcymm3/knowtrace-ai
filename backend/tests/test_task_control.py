import asyncio
from uuid import UUID, uuid4

from app.features.tasks.service import TaskControlService


class FakeTaskStore:
    def __init__(self, workspace_id: UUID, document_id: UUID, task_type: str, status: str) -> None:
        self.workspace_id = workspace_id
        self.document_id = document_id
        self.tasks: dict[UUID, dict[str, object]] = {}
        self.document: dict[str, object] = {
            "id": str(document_id),
            "workspace_id": str(workspace_id),
            "storage_bucket": "knowtrace-assets",
            "storage_path": f"{workspace_id}/{document_id}/original/source.txt",
            "status": "FAILED",
            "error_message": "provider unavailable",
            "metadata": {
                "extractedTextPath": f"{workspace_id}/{document_id}/derived/extracted.txt"
            },
        }
        task_id = uuid4()
        self.task_id = task_id
        self.tasks[task_id] = {
            "id": str(task_id),
            "workspace_id": str(workspace_id),
            "document_id": str(document_id),
            "task_type": task_type,
            "status": status,
            "progress": 100,
            "attempt_count": 3,
            "max_attempts": 3,
            "input_payload": {},
            "output_payload": {},
            "error_message": "provider unavailable",
            "started_at": None,
            "completed_at": None,
        }
        self.deleted_storage: tuple[str, list[str]] | None = None
        self.deleted_document_id: UUID | None = None

    def get_task(self, task_id: UUID) -> dict[str, object]:
        return self.tasks[task_id]

    def get_document(self, _document_id: UUID) -> dict[str, object]:
        return self.document

    def update_task(self, task_id: UUID, data: dict[str, object]) -> None:
        self.tasks[task_id].update(data)

    def update_document(self, _document_id: UUID, data: dict[str, object]) -> None:
        self.document.update(data)

    def create_task(self, data: dict[str, object]) -> dict[str, object]:
        task_id = UUID(str(data["id"]))
        task = {
            **data,
            "progress": 0,
            "attempt_count": 0,
            "max_attempts": 3,
            "output_payload": {},
            "error_message": None,
            "started_at": None,
            "completed_at": None,
        }
        self.tasks[task_id] = task
        return task

    def delete_storage_files(self, bucket: str, paths: list[str]) -> None:
        self.deleted_storage = (bucket, paths)

    def delete_document_records(self, document_id: UUID) -> None:
        self.deleted_document_id = document_id


class FakeTaskQueue:
    def __init__(self) -> None:
        self.parse_ids: list[UUID] = []
        self.embedding_ids: list[UUID] = []

    async def enqueue_parse_document(self, task_id: UUID) -> None:
        self.parse_ids.append(task_id)

    async def enqueue_generate_embeddings(self, task_id: UUID) -> None:
        self.embedding_ids.append(task_id)


def test_retry_failed_parse_creates_a_fresh_task_and_queues_it() -> None:
    workspace_id, document_id = uuid4(), uuid4()
    store = FakeTaskStore(workspace_id, document_id, "PARSE_DOCUMENT", "FAILED")
    queue = FakeTaskQueue()
    service = TaskControlService(store=store, queue=queue)  # type: ignore[arg-type]

    retried = asyncio.run(service.retry_task(workspace_id, store.task_id))

    assert retried["status"] == "QUEUED"
    assert retried["input_payload"] == {
        "documentId": str(document_id),
        "retryOf": str(store.task_id),
    }
    assert store.document["status"] == "PENDING"
    assert store.document["error_message"] is None
    assert queue.parse_ids == [UUID(str(retried["id"]))]


def test_cancel_embedding_keeps_parsed_text_available_for_retry() -> None:
    workspace_id, document_id = uuid4(), uuid4()
    store = FakeTaskStore(workspace_id, document_id, "GENERATE_EMBEDDINGS", "RUNNING")
    service = TaskControlService(store=store, queue=FakeTaskQueue())  # type: ignore[arg-type]

    cancelled = asyncio.run(service.cancel_task(workspace_id, store.task_id))

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["error_message"] == "已由用户取消。"
    assert store.document["status"] == "PARSED"
    assert store.document["error_message"] == "处理已取消，可重新尝试。"


def test_delete_document_removes_storage_artifacts_and_database_records() -> None:
    workspace_id, document_id = uuid4(), uuid4()
    store = FakeTaskStore(workspace_id, document_id, "PARSE_DOCUMENT", "FAILED")
    service = TaskControlService(store=store, queue=FakeTaskQueue())  # type: ignore[arg-type]

    asyncio.run(service.delete_document(workspace_id, document_id))

    assert store.deleted_storage == (
        "knowtrace-assets",
        [
            f"{workspace_id}/{document_id}/original/source.txt",
            f"{workspace_id}/{document_id}/derived/extracted.txt",
        ],
    )
    assert store.deleted_document_id == document_id

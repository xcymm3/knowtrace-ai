from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class TaskStatusResponse(BaseModel):
    id: UUID
    project_id: UUID
    document_id: UUID | None
    task_type: str
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
    progress: int
    attempt_count: int
    max_attempts: int
    output_payload: dict[str, object]
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None

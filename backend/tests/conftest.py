from uuid import UUID, uuid4

import pytest

from app.api.auth import CurrentUser, get_current_user, get_owned_workspace_id
from app.api.v1.tasks import get_owned_task_id
from app.main import app


@pytest.fixture(autouse=True)
def authenticated_api_client() -> None:
    """Keep existing domain route tests focused on their own concern.

    Authentication and ownership are exercised separately; route tests receive a
    deterministic authenticated owner and preserve the workspace/task path IDs.
    """

    user = CurrentUser(id=uuid4(), email="tester@example.com")

    def owned_workspace(workspace_id: UUID) -> UUID:
        return workspace_id

    def owned_task(task_id: UUID) -> UUID:
        return task_id

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_owned_workspace_id] = owned_workspace
    app.dependency_overrides[get_owned_task_id] = owned_task
    yield
    app.dependency_overrides.clear()

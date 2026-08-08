from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import anyio
from fastapi import Depends, Header

from app.api.dependencies import get_workspace_service
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.features.documents.store import create_supabase_client
from app.features.workspaces.service import WorkspaceService


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str | None


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise ApiError(401, "AUTHENTICATION_REQUIRED", "请先登录后再访问个人知识库。")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError(401, "AUTHORIZATION_INVALID", "登录凭证格式无效，请重新登录。")
    return token.strip()


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """Validate a Supabase user JWT on the Auth service before every domain request."""
    token = _bearer_token(authorization)
    try:
        response = await anyio.to_thread.run_sync(
            create_supabase_client(settings).auth.get_user,
            token,
        )
        user = response.user
        if user is None or not user.id:
            raise ValueError("Supabase did not return a user")
        return CurrentUser(id=UUID(str(user.id)), email=user.email)
    except ApiError:
        raise
    except Exception as error:
        raise ApiError(401, "AUTHENTICATION_INVALID", "登录已失效，请重新登录。") from error


async def get_owned_workspace_id(
    workspace_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
) -> UUID:
    await service.get_workspace(workspace_id, current_user.id)
    return workspace_id

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import ApiError
from app.features.authentication.schemas import (
    UsernameAvailabilityResponse,
    UsernameSignInRequest,
    UsernameSignInResponse,
)
from app.features.documents.store import create_supabase_client


class UsernameSignInService:
    """Resolve a username on the server, then let Supabase Auth issue the session."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def username_availability(self, username: str) -> UsernameAvailabilityResponse:
        normalized_username = username.strip().lower()
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,32}", normalized_username):
            raise ApiError(
                422,
                "USERNAME_INVALID",
                "用户名需为 3–32 位字母、数字、下划线或连字符。",
            )

        try:
            response = (
                create_supabase_client(self._settings)
                .table("profiles")
                .select("id")
                .eq("username", normalized_username)
                .limit(1)
                .execute()
            )
        except ApiError:
            raise
        except Exception as error:
            raise ApiError(
                503,
                "USERNAME_CHECK_UNAVAILABLE",
                "暂时无法检查用户名，请稍后重试。",
            ) from error
        return UsernameAvailabilityResponse(available=not bool(response.data))

    def _resolve_email(self, identity: str) -> str:
        normalized_identity = identity.strip().lower()
        if "@" in normalized_identity:
            return normalized_identity

        try:
            response = (
                create_supabase_client(self._settings)
                .table("profiles")
                .select("email")
                .eq("username", normalized_identity)
                .limit(1)
                .execute()
            )
        except ApiError:
            raise
        except Exception as error:
            raise ApiError(
                503,
                "USERNAME_LOGIN_UNAVAILABLE",
                "用户名登录尚未完成初始化，请先使用邮箱登录。",
            ) from error
        if not response.data:
            raise ApiError(401, "SIGN_IN_FAILED", "用户名或密码不正确。")
        return str(response.data[0]["email"])

    async def sign_in(self, payload: UsernameSignInRequest) -> UsernameSignInResponse:
        email = await asyncio.to_thread(self._resolve_email, payload.identity)
        auth_url = (
            f"{(self._settings.supabase_url or '').rstrip('/')}"
            "/auth/v1/token?grant_type=password"
        )
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.post(
                    auth_url,
                    headers={"apikey": self._settings.supabase_service_role_key or ""},
                    json={"email": email, "password": payload.password},
                )
        except httpx.HTTPError as error:
            raise ApiError(
                503,
                "AUTH_PROVIDER_UNAVAILABLE",
                "登录服务暂时不可用，请稍后重试。",
            ) from error

        if response.status_code != 200:
            raise ApiError(401, "SIGN_IN_FAILED", "用户名或密码不正确。")
        data: Any = response.json()
        try:
            return UsernameSignInResponse(
                access_token=str(data["access_token"]),
                refresh_token=str(data["refresh_token"]),
                expires_in=int(data["expires_in"]),
                token_type=str(data["token_type"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ApiError(502, "AUTH_RESPONSE_INVALID", "登录服务返回了无效结果。") from error

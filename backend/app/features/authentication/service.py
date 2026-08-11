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
    UsernameSignUpRequest,
)
from app.features.documents.store import create_supabase_client


class UsernameSignInService:
    """Provide username-only credentials on top of Supabase's email/password Auth."""

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

    def _resolve_email(self, username: str) -> str:
        normalized_username = username.strip().lower()
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,32}", normalized_username):
            raise ApiError(401, "SIGN_IN_FAILED", "用户名或密码不正确。")
        try:
            response = (
                create_supabase_client(self._settings)
                .table("profiles")
                .select("email")
                .eq("username", normalized_username)
                .limit(1)
                .execute()
            )
        except ApiError:
            raise
        except Exception as error:
            raise ApiError(
                503,
                "USERNAME_LOGIN_UNAVAILABLE",
                "用户名登录服务暂时不可用，请稍后重试。",
            ) from error
        if not response.data:
            raise ApiError(401, "SIGN_IN_FAILED", "用户名或密码不正确。")
        return str(response.data[0]["email"])

    @staticmethod
    def _internal_email(username: str) -> str:
        return f"{username}@users.knowtrace.invalid"

    async def sign_up(self, payload: UsernameSignUpRequest) -> UsernameSignInResponse:
        username = payload.username.strip().lower()
        availability = await asyncio.to_thread(self.username_availability, username)
        if not availability.available:
            raise ApiError(409, "USERNAME_TAKEN", "用户名已被使用，请换一个。")

        if not self._settings.supabase_url or not self._settings.supabase_service_role_key:
            raise ApiError(503, "AUTH_PROVIDER_UNAVAILABLE", "登录服务暂时不可用，请稍后重试。")

        auth_url = f"{self._settings.supabase_url.rstrip('/')}/auth/v1/admin/users"
        service_key = self._settings.supabase_service_role_key
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.post(
                    auth_url,
                    headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
                    json={
                        "email": self._internal_email(username),
                        "password": payload.password,
                        "email_confirm": True,
                        "user_metadata": {"username": username},
                    },
                )
        except httpx.HTTPError as error:
            raise ApiError(
                503,
                "AUTH_PROVIDER_UNAVAILABLE",
                "登录服务暂时不可用，请稍后重试。",
            ) from error

        if response.status_code in {400, 409, 422}:
            raise ApiError(409, "USERNAME_TAKEN", "用户名已被使用，请换一个。")
        if response.status_code not in {200, 201}:
            raise ApiError(502, "AUTH_PROVIDER_INVALID_RESPONSE", "账号创建失败，请稍后重试。")

        return await self.sign_in(UsernameSignInRequest(identity=username, password=payload.password))

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

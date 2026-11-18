import os
from codecs import BOM_UTF8
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.features.agent.anthropic import AnthropicMessagesModel
from app.features.agent.model import ChatCompletionsModel
from app.features.agent.runtime import AgentError, ChatModel

LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class ModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    protocol: Literal["openai-chat", "anthropic-messages"]
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=256)
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    auth: Literal["api-key", "bearer"] | None = None
    token_field: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"


def http_url(value: str, label: str) -> str:
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL as error:
        raise AgentError(f"{label}地址格式无效。") from error
    if (
        url.userinfo
        or url.query
        or url.fragment
        or not url.host
        or not (url.scheme == "https" or (url.scheme == "http" and url.host in LOOPBACK))
    ):
        raise AgentError(f"{label}地址须使用 HTTPS 或本机 HTTP，且不能携带凭证或参数。")
    return str(url).rstrip("/")


def connect_profile(client: httpx.AsyncClient, path: Path, name: str) -> ChatModel:
    try:
        with path.open("rb") as file:
            raw = file.read(65_537)
        if len(raw) > 65_536:
            raise AgentError("模型配置文件超过 64 KiB。")
        profiles = TypeAdapter(dict[str, ModelProfile]).validate_json(raw.removeprefix(BOM_UTF8))
    except (OSError, ValidationError) as error:
        raise AgentError("无法读取模型配置，请检查 JSON 格式与字段。") from error
    profile = profiles.get(name)
    if profile is None:
        raise AgentError("模型配置中没有该档案。")

    url = http_url(profile.base_url, "模型服务")
    api_key = ""
    if profile.api_key_env:
        api_key = os.environ.get(profile.api_key_env, "").strip()
        if not api_key:
            raise AgentError(f"请设置模型档案引用的环境变量 {profile.api_key_env}。")
    elif httpx.URL(url).host not in LOOPBACK:
        raise AgentError("远程模型档案须通过 api_key_env 指定密钥。")
    if profile.protocol == "anthropic-messages":
        if profile.token_field != "max_tokens":
            raise AgentError("Messages API 档案使用 max_tokens。")
        return AnthropicMessagesModel(
            client, url, api_key, profile.model, bearer_auth=profile.auth == "bearer"
        )
    if profile.auth == "api-key":
        raise AgentError("Chat Completions 档案使用 Bearer 认证。")
    return ChatCompletionsModel(
        client, url, api_key, profile.model, token_field=profile.token_field
    )

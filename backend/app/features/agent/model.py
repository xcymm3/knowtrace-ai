from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.features.agent.runtime import AgentError, Message, ToolCall


@asynccontextmanager
async def model_stream(
    client: httpx.AsyncClient, url: str, headers: dict[str, str], payload: dict[str, Any]
) -> AsyncIterator[httpx.Response]:
    try:
        async with client.stream(
            "POST", url, headers=headers, json=payload, follow_redirects=False
        ) as response:
            response.raise_for_status()
            yield response
    except httpx.HTTPStatusError as error:
        raise AgentError(f"模型服务返回 HTTP {error.response.status_code}。") from error
    except httpx.RequestError as error:
        raise AgentError("模型服务连接失败或响应中断。") from error


async def stream_data(response: httpx.Response) -> AsyncIterator[str]:
    parts: list[str] = []
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            parts.append(line[5:].removeprefix(" "))
        elif not line and parts:
            yield "\n".join(parts)
            parts.clear()


class _FunctionDelta(BaseModel):
    name: str | None = None
    arguments: str | None = None


class _ToolDelta(BaseModel):
    index: int = Field(ge=0, lt=24)
    id: str | None = None
    type: str | None = None
    function: _FunctionDelta | None = None


class _MessageDelta(BaseModel):
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[_ToolDelta] | None = None


class _Choice(BaseModel):
    delta: _MessageDelta = Field(default_factory=_MessageDelta)
    finish_reason: str | None = None


class _Chunk(BaseModel):
    choices: list[_Choice] = Field(max_length=1)


@dataclass
class _PendingCall:
    id: str = ""
    name: str = ""
    arguments: list[str] = field(default_factory=list)

    def append(self, delta: _ToolDelta) -> None:
        if delta.type not in (None, "function") or (delta.id and self.id and delta.id != self.id):
            raise AgentError("模型返回了无效的工具调用。")
        if delta.id:
            self.id = delta.id
        if delta.function:
            if delta.function.name:
                self.name += delta.function.name
            if delta.function.arguments:
                self.arguments.append(delta.function.arguments)


def _message_payload(message: Message) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.reasoning is not None:
        payload["reasoning_content"] = message.reasoning
    if message.tool_call_id is not None:
        payload["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in message.tool_calls
        ]
    return payload


class ChatCompletionsModel:
    """OpenAI-compatible streaming adapter that preserves DeepSeek thinking messages."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: str,
        model: str,
        *,
        token_field: str = "max_tokens",
    ) -> None:
        self._client = client
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._model = model
        self._token_field = token_field

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        on_text: Callable[[str], None],
    ) -> Message:
        payload = {
            "model": self._model,
            "messages": [_message_payload(message) for message in messages],
            "stream": True,
            self._token_field: 4096,
        }
        if tools:
            payload["tools"] = tools
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        try:
            async with model_stream(self._client, self._url, headers, payload) as response:
                return await self._read_stream(response, on_text)
        except ValidationError as error:
            raise AgentError("模型返回了无效的流式数据。") from error

    @staticmethod
    async def _read_stream(response: httpx.Response, on_text: Callable[[str], None]) -> Message:
        content: list[str] = []
        reasoning: list[str] = []
        pending: dict[int, _PendingCall] = {}
        finish_reason: str | None = None
        done = False

        async for data in stream_data(response):
            if data.strip() == "[DONE]":
                done = True
                break
            chunk = _Chunk.model_validate_json(data)
            for choice in chunk.choices:
                delta = choice.delta
                if delta.content:
                    content.append(delta.content)
                    on_text(delta.content)
                if delta.reasoning_content is not None:
                    reasoning.append(delta.reasoning_content)
                for tool in delta.tool_calls or ():
                    pending.setdefault(tool.index, _PendingCall()).append(tool)
                if choice.finish_reason is not None:
                    finish_reason = choice.finish_reason

        if not done or finish_reason not in {"stop", "tool_calls"}:
            raise AgentError("模型未正常完成响应，可能已中断或达到输出上限。")
        calls = tuple(
            ToolCall(call.id, call.name, "".join(call.arguments))
            for _, call in sorted(pending.items())
        )
        if (
            (finish_reason == "tool_calls") != bool(calls)
            or any(not call.id or not call.name for call in calls)
            or len({call.id for call in calls}) != len(calls)
        ):
            raise AgentError("模型返回了不完整或重复的工具调用。")
        return Message(
            "assistant",
            "".join(content),
            tool_calls=calls,
            reasoning="".join(reasoning) if reasoning else None,
        )

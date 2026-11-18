import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.features.agent.model import model_stream, stream_data
from app.features.agent.runtime import AgentError, Message, ToolCall


class _Event(BaseModel):
    type: str
    index: int | None = Field(default=None, ge=0, lt=128)
    content_block: dict[str, Any] | None = None
    delta: dict[str, Any] | None = None


@dataclass
class _Block:
    data: dict[str, Any]
    partial_input: list[str] = field(default_factory=list)

    def apply(self, delta: dict[str, Any], on_text: Callable[[str], None]) -> None:
        name = delta.get("type")
        if name == "input_json_delta":
            self.partial_input.append(_text(delta, "partial_json"))
        elif name in ("text_delta", "thinking_delta", "signature_delta"):
            key = name.removesuffix("_delta")
            value = _text(delta, key)
            self.data[key] = self.data.get(key, "") + value
            if key == "text" and value:
                on_text(value)

    def finish(self) -> None:
        data = "".join(self.partial_input)
        if data.strip():
            self.data["input"] = json.loads(data)


def _text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise AgentError("Messages API 返回了无效的内容块。")
    return value


def _message_payload(messages: list[Message]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            content = [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": message.content,
                }
            ]
        else:
            content = list(message.provider_content) or [{"type": "text", "text": message.content}]
        role = "user" if message.role == "tool" else message.role
        if payload and payload[-1]["role"] == role:
            payload[-1]["content"].extend(content)
        else:
            payload.append({"role": role, "content": content})
    return payload


class AnthropicMessagesModel:
    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: str,
        model: str,
        *,
        bearer_auth: bool = False,
    ) -> None:
        self._client = client
        base = base_url.rstrip("/")
        self._url = f"{base.removesuffix('/v1')}/v1/messages"
        self._headers = {"anthropic-version": "2023-06-01"}
        if api_key:
            if bearer_auth:
                self._headers["Authorization"] = f"Bearer {api_key}"
            else:
                self._headers["x-api-key"] = api_key
        self._model = model

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        on_text: Callable[[str], None],
    ) -> Message:
        payload = {
            "model": self._model,
            "max_tokens": 4096,
            "stream": True,
            "messages": _message_payload(messages),
        }
        system = "\n\n".join(message.content for message in messages if message.role == "system")
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": function["name"],
                    "description": function["description"],
                    "input_schema": function["parameters"],
                }
                for tool in tools
                for function in (tool["function"],)
            ]
        try:
            async with model_stream(self._client, self._url, self._headers, payload) as response:
                return await self._read_stream(response, on_text)
        except (ValidationError, json.JSONDecodeError, TypeError) as error:
            raise AgentError("Messages API 返回了无效的流式数据。") from error

    @staticmethod
    async def _read_stream(response: httpx.Response, on_text: Callable[[str], None]) -> Message:
        pending: dict[int, _Block] = {}
        complete: dict[int, dict[str, Any]] = {}
        stop_reason = None
        ended = False
        async for data in stream_data(response):
            if data.strip() == "[DONE]":
                ended = True
                break
            event = _Event.model_validate_json(data)
            if event.type == "error":
                raise AgentError("Messages API 在响应流中返回了错误。")
            if event.type == "message_stop":
                ended = True
                break
            if event.type == "message_delta" and event.delta:
                stop_reason = event.delta.get("stop_reason") or stop_reason
            index = event.index
            if event.type == "content_block_start":
                if (
                    index is None
                    or index in pending
                    or index in complete
                    or not event.content_block
                ):
                    raise AgentError("Messages API 返回了无效的内容块索引。")
                block_data = event.content_block
                pending[index] = _Block(block_data)
                if block_data.get("type") == "text" and (text := _text(block_data, "text")):
                    on_text(text)
            if event.type in {"content_block_delta", "content_block_stop"}:
                if index is None or index not in pending:
                    raise AgentError("Messages API 返回了无效的内容块索引。")
                block = pending[index]
                if event.type == "content_block_delta" and event.delta is not None:
                    block.apply(event.delta, on_text)
                elif event.type == "content_block_stop":
                    block.finish()
                    complete[index] = pending.pop(index).data

        if not ended or pending or stop_reason not in {"end_turn", "stop_sequence", "tool_use"}:
            raise AgentError("Messages API 未正常完成响应，可能已中断或达到输出上限。")
        blocks = tuple(block for _, block in sorted(complete.items()))
        calls = []
        for block in blocks:
            if block.get("type") == "tool_use":
                tool_id, name = _text(block, "id"), _text(block, "name")
                arguments = block.get("input")
                if not tool_id or not name or not isinstance(arguments, dict):
                    raise AgentError("Messages API 返回了无效的工具调用。")
                calls.append(ToolCall(tool_id, name, json.dumps(arguments, ensure_ascii=False)))
        if (stop_reason == "tool_use") != bool(calls) or len({call.id for call in calls}) != len(
            calls
        ):
            raise AgentError("Messages API 返回了不完整或重复的工具调用。")
        text = "".join(_text(block, "text") for block in blocks if block.get("type") == "text")
        return Message("assistant", text, tuple(calls), provider_content=blocks)

import json
from dataclasses import dataclass
from uuid import uuid4

from app.features.agent.runtime import AgentError, ChatModel, Message


@dataclass(frozen=True)
class Capabilities:
    text_streaming: bool
    tool_calling: bool
    tool_round_trip: bool
    detail: str


async def probe_model(model: ChatModel) -> Capabilities:
    chunks: list[str] = []
    text = await model.complete([Message("user", "Reply with OK.")], [], chunks.append)
    if not text.content.strip() or not "".join(chunks).strip() or text.tool_calls:
        raise AgentError("未通过文本流探测。")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "knowtrace_probe",
                "description": "Returns a receipt string. This synthetic tool has no side effects.",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            },
        }
    ]
    messages = [
        Message(
            "user",
            'Call knowtrace_probe once with {"value":"ping"}, then reply with its receipt exactly.',
        )
    ]
    try:
        reply = await model.complete(messages, tools, lambda _: None)
        if len(reply.tool_calls) != 1:
            return Capabilities(True, False, False, "探测未收到预期的工具调用。")
        call = reply.tool_calls[0]
        if call.name != "knowtrace_probe" or json.loads(call.arguments) != {"value": "ping"}:
            return Capabilities(True, False, False, "探测收到的工具参数与契约不匹配。")
    except (AgentError, json.JSONDecodeError) as error:
        detail = str(error) if isinstance(error, AgentError) else "工具参数不是有效 JSON。"
        return Capabilities(True, False, False, detail)
    receipt = f"probe-{uuid4().hex[:12]}"
    messages.extend(
        (reply, Message("tool", json.dumps({"receipt": receipt}), tool_call_id=call.id))
    )
    try:
        result = await model.complete(messages, tools, lambda _: None)
    except AgentError as error:
        return Capabilities(True, True, False, str(error))
    if result.tool_calls or receipt not in result.content:
        return Capabilities(True, True, False, "探测未确认模型读取了工具回执。")
    return Capabilities(True, True, True, "文本流与工具往返均通过。")

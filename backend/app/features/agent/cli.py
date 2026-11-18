import argparse
import asyncio
import re
import sys
from pathlib import Path
from uuid import UUID

import httpx
from pydantic import AliasChoices, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings

from app.core.config import Settings
from app.features.agent.files import WorkspaceFiles
from app.features.agent.model import ChatCompletionsModel
from app.features.agent.runtime import AgentError, run_agent
from app.features.agent.tools import KnowledgeClient, ReadOnlyTools


class CliSettings(BaseSettings):
    model_config = Settings.model_config

    agent_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("AGENT_API_KEY", "DEEPSEEK_API_KEY")
    )
    agent_base_url: str = ""
    agent_model: str = ""
    knowtrace_api_base_url: str = "http://127.0.0.1:8000"
    knowtrace_access_token: SecretStr | None = None

    def model_connection(self) -> tuple[str, str, str]:
        key = self.agent_api_key.get_secret_value().strip() if self.agent_api_key else ""
        if key:
            return (
                self.agent_base_url.strip() or "https://api.deepseek.com",
                key,
                self.agent_model.strip() or "deepseek-flash",
            )
        if not (self.agent_base_url or self.agent_model):
            settings = Settings()
            if settings.llm_is_configured:
                return (
                    (settings.llm_base_url or "").strip(),
                    (settings.llm_api_key or "").strip(),
                    settings.llm_model.strip(),
                )
        raise AgentError("请设置 AGENT_API_KEY 或 DEEPSEEK_API_KEY。")


def _http_url(value: str, label: str) -> str:
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL as error:
        raise AgentError(f"{label}地址格式无效。") from error
    if (
        url.userinfo
        or url.query
        or url.fragment
        or not url.host
        or not (
            url.scheme == "https"
            or (url.scheme == "http" and url.host in {"localhost", "127.0.0.1", "::1"})
        )
    ):
        raise AgentError(f"{label}地址须使用 HTTPS 或本机 HTTP，且不能携带凭证或参数。")
    return str(url).rstrip("/")


def _console(text: str) -> str:
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", text)


async def _run(args: argparse.Namespace) -> None:
    settings = CliSettings()
    token = settings.knowtrace_access_token
    if not token or not token.get_secret_value().strip():
        raise AgentError("请设置 KNOWTRACE_ACCESS_TOKEN 为当前用户的 Supabase Access Token。")
    model_url, api_key, model_name = settings.model_connection()
    model_url = _http_url(model_url, "模型服务")
    knowledge_url = _http_url(args.api_base_url or settings.knowtrace_api_base_url, "KnowTrace")
    try:
        files = WorkspaceFiles(args.root)
    except (OSError, RuntimeError, ValueError) as error:
        raise AgentError("授权路径必须是当前用户可访问的目录。") from error

    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as client:
        model = ChatCompletionsModel(client, model_url, api_key, model_name)
        knowledge = KnowledgeClient(
            client, knowledge_url, args.workspace_id, token.get_secret_value().strip()
        )
        tools = ReadOnlyTools(knowledge, files)
        await run_agent(
            model,
            tools,
            args.task.strip(),
            max_steps=args.max_steps,
            on_text=lambda delta: print(_console(delta), end="", flush=True),
            on_tool=lambda name: print(f"\n[工具] {_console(name)}", file=sys.stderr, flush=True),
        )

    print()
    if tools.sources:
        print("\n本次检索来源")
        for label, hit in tools.sources.values():
            citation = hit.citation
            print(
                f"[{label}] {_console(citation.file_name)} · "
                f"片段 {citation.chunk_index + 1} · {hit.chunk_id}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.features.agent",
        description="通过知识库和本地文件回答问题的只读 Agent",
    )
    parser.add_argument("--root", type=Path, required=True, help="授权读取的本地目录")
    parser.add_argument("--workspace-id", type=UUID, required=True, help="KnowTrace 知识库 ID")
    parser.add_argument("--api-base-url", help="KnowTrace API 基础地址，默认 http://127.0.0.1:8000")
    parser.add_argument("--max-steps", type=int, default=8, metavar="N", help="模型请求轮数上限")
    parser.add_argument("task", help="交给 Agent 的任务")
    args = parser.parse_args(argv)
    if not 1 <= args.max_steps <= 20 or not 1 <= len(args.task.strip()) <= 8000:
        parser.error("轮数须在 1–20 之间，任务须包含 1–8000 个字符。")
    try:
        asyncio.run(_run(args))
    except ValidationError:
        print("Agent 环境配置格式无效。", file=sys.stderr)
        return 2
    except AgentError as error:
        print(f"\nAgent 运行失败：{error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nAgent 运行已取消。", file=sys.stderr)
        return 130
    return 0

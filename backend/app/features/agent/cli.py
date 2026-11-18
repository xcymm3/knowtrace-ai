import argparse
import asyncio
import re
import sys
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from pydantic import AliasChoices, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings

from app.core.config import Settings
from app.features.agent.checks import Verification, load_commands
from app.features.agent.edits import FileChanges, journal_path
from app.features.agent.executor import ExecutorClient, serve
from app.features.agent.files import WorkspaceFiles
from app.features.agent.model import ChatCompletionsModel
from app.features.agent.runtime import AgentError, run_agent
from app.features.agent.tools import BatchTool, KnowledgeClient, PatchTool, WorkspaceTools
from app.features.agent.worktree import create_worktree, project_rules


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


def _workspace_files(root: Path) -> WorkspaceFiles:
    try:
        return WorkspaceFiles(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise AgentError("授权路径必须是当前用户可访问的目录。") from error


def _confirm(diff: str) -> bool:
    print(f"\n{_console(diff)}", end="", flush=True)
    try:
        return input("确认应用以上变更？[y/N] ").strip().casefold() == "y"
    except EOFError:
        return False


def _patch_tool(files: WorkspaceFiles) -> PatchTool:
    changes = FileChanges(files, journal_path())

    async def apply_patch(path: str, old_text: str, new_text: str) -> dict[str, str]:
        result = changes.apply(path, old_text, new_text, _confirm)
        if result["status"] == "applied":
            print(
                f"\n已写入 {_console(result['path'])} · 回退 ID {result['change_id']}",
                flush=True,
            )
        return result

    return apply_patch


def _batch_tool(changes: FileChanges) -> BatchTool:
    rejected = False

    async def apply_patches(edits):
        nonlocal rejected
        if rejected:
            raise ValueError("用户已拒绝修改。")
        prepared = changes.prepare_many(edits)
        if not _confirm("".join(edit.diff for edit in prepared)):
            rejected = True
            return {"status": "rejected"}
        change_id = changes.commit_many(prepared)
        print(f"\n已写入 {len(prepared)} 个文件 · 回退 ID {change_id}", flush=True)
        return {
            "status": "applied",
            "paths": [edit.path for edit in prepared],
            "change_id": change_id,
        }

    return apply_patches


def _undo(root: Path, change_id: UUID) -> None:
    changes = FileChanges(_workspace_files(root), journal_path())
    try:
        restored = changes.undo(change_id, _confirm)
    except OSError as error:
        raise AgentError("无法访问本地文件或回退记录。") from error
    except ValueError as error:
        raise AgentError(str(error)) from error
    print("已回退该次修改。" if restored else "已取消回退。")


async def _run(args: argparse.Namespace) -> None:
    settings = CliSettings()
    token = settings.knowtrace_access_token
    if not token or not token.get_secret_value().strip():
        raise AgentError("请设置 KNOWTRACE_ACCESS_TOKEN 为当前用户的 Supabase Access Token。")
    model_url, api_key, model_name = settings.model_connection()
    model_url = _http_url(model_url, "模型服务")
    knowledge_url = _http_url(args.api_base_url or settings.knowtrace_api_base_url, "KnowTrace")
    files = _workspace_files(args.root)
    commands = load_commands(args.commands)
    rules = ""
    verification = None
    batch = None
    if args.worktree:
        journal = journal_path()
        worktree = create_worktree(files, journal.parent, uuid4())
        files = worktree.files
        rules = project_rules(files)
        verification = Verification(files.root, commands)
        batch = _batch_tool(FileChanges(files, journal))
        print(f"隔离工作树：{files.root}\nGit 基线：{worktree.base_commit}", flush=True)

    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as client:
        model = ChatCompletionsModel(client, model_url, api_key, model_name)
        knowledge = KnowledgeClient(
            client, knowledge_url, args.workspace_id, token.get_secret_value().strip()
        )
        if args.serve:
            await serve(
                ExecutorClient(
                    client, knowledge_url, args.workspace_id, token.get_secret_value().strip()
                ),
                args.executor_id or uuid4(),
                files,
                model,
                knowledge,
                args.max_steps,
                commands,
            )
            return
        tools = WorkspaceTools(
            knowledge,
            files,
            _patch_tool(files) if args.edit else None,
            apply_patches=batch,
            verification=verification,
        )
        await run_agent(
            model,
            tools,
            args.task.strip(),
            max_steps=args.max_steps,
            on_text=lambda delta: print(_console(delta), end="", flush=True),
            on_tool=lambda name: print(f"\n[工具] {_console(name)}", file=sys.stderr, flush=True),
            edit=args.edit or args.worktree,
            project_rules=rules,
            verify=verification.feedback if verification else None,
        )

    print()
    if verification is not None and verification.results:
        print("当前版本的检查结果")
        for name, result in verification.results.items():
            print(f"{name} · 退出码 {result['exit_code']}")
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
        description="结合知识库查询和修改本地文件的 Agent",
    )
    parser.add_argument("--root", type=Path, required=True, help="授权读取的本地目录")
    parser.add_argument("--workspace-id", type=UUID, help="KnowTrace 知识库 ID")
    parser.add_argument("--api-base-url", help="KnowTrace API 基础地址，默认 http://127.0.0.1:8000")
    parser.add_argument("--max-steps", type=int, metavar="N", help="模型请求轮数上限")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--edit", action="store_true", help="启用经确认的文件修改")
    mode.add_argument("--undo", type=UUID, metavar="ID", help="按修改 ID 预览和回退")
    mode.add_argument("--serve", action="store_true", help="领取 Web 工作台的 Agent 任务")
    mode.add_argument("--worktree", action="store_true", help="在独立 Git 工作树中执行任务")
    parser.add_argument("--commands", type=Path, help="授权验证命令的本地 JSON 清单")
    parser.add_argument("--executor-id", type=UUID, help="复用工作台中已选定的执行器 ID")
    parser.add_argument("task", nargs="?", help="交给 Agent 的任务")
    args = parser.parse_args(argv)
    if args.max_steps is None:
        args.max_steps = 16 if args.serve or args.worktree else 8
    if args.commands is not None and not (args.serve or args.worktree):
        parser.error("--commands 仅适用于 --serve 或 --worktree。")
    if args.executor_id is not None and not args.serve:
        parser.error("--executor-id 须与 --serve 一起使用。")
    try:
        if args.undo is not None:
            if args.task is not None:
                parser.error("回退只需指定 --root 和 --undo ID。")
            _undo(args.root, args.undo)
        else:
            if args.workspace_id is None:
                parser.error("运行 Agent 须提供 --workspace-id。")
            if not 1 <= args.max_steps <= 20:
                parser.error("轮数须在 1–20 之间。")
            if args.serve and args.task is not None:
                parser.error("本地执行器从 Web 工作台领取任务。")
            if not args.serve and not 1 <= len((args.task or "").strip()) <= 8000:
                parser.error("任务须包含 1–8000 个字符。")
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

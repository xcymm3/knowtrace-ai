import asyncio
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import httpx
from pydantic import ValidationError

from app.features.agent.checks import CommandMap, Verification
from app.features.agent.edits import FileChanges, PreparedEdit, journal_path
from app.features.agent.files import WorkspaceFiles
from app.features.agent.runs import MAX_APPROVALS, MAX_DIFF, RunSnapshot
from app.features.agent.runtime import AgentError, ChatModel, Message, ToolCall, run_agent
from app.features.agent.tools import KnowledgeClient, WorkspaceTools
from app.features.agent.worktree import create_worktree, project_rules


class RunCancelled(AgentError):
    pass


class ExecutorClient:
    def __init__(
        self, http: httpx.AsyncClient, base_url: str, workspace: UUID, access_token: str
    ) -> None:
        api = base_url.rstrip("/").removesuffix("/api/v1") + "/api/v1"
        self.url = f"{api}/workspaces/{workspace}/agent/runs"
        self.http = http
        self.headers = {"Authorization": f"Bearer {access_token}"}

    async def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> RunSnapshot | None:
        delay = 1
        while True:
            try:
                response = await self.http.request(
                    method, self.url + path, headers=self.headers, json=body, timeout=15
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                pass
            else:
                if response.is_success:
                    if response.content.strip() == b"null":
                        return None
                    try:
                        return RunSnapshot.model_validate_json(response.content)
                    except ValidationError as error:
                        if error.errors(include_input=False)[0]["type"] != "json_invalid":
                            raise AgentError("Agent 控制接口返回的任务状态不兼容。") from error
                elif response.status_code < 500 and response.status_code not in (408, 429):
                    raise AgentError(f"Agent 控制接口返回 HTTP {response.status_code}。")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 8)

    async def claim(self, executor_id: UUID, claim_id: UUID) -> RunSnapshot | None:
        return await self._request(
            "POST", "/claim", {"executor_id": str(executor_id), "claim_id": str(claim_id)}
        )

    async def get(self, run_id: UUID) -> RunSnapshot:
        snapshot = await self._request("GET", f"/{run_id}")
        if snapshot is None:
            raise AgentError("服务未返回任务状态。")
        return snapshot

    async def operation(
        self, run_id: UUID, claim_id: UUID, action: str, **data: Any
    ) -> RunSnapshot:
        # Keep the operation ID stable across a timeout or lost HTTP response.
        body = {"claim_id": str(claim_id), "op_id": str(uuid4()), "action": action, **data}
        snapshot = await self._request("POST", f"/{run_id}/executor", body)
        if snapshot is None:
            raise AgentError("服务未返回执行结果。")
        return snapshot


class LocalRun:
    def __init__(
        self, client: ExecutorClient, run: RunSnapshot, claim_id: UUID, changes: FileChanges
    ) -> None:
        self.client = client
        self.id = run.id
        self.claim_id = claim_id
        self.changes = changes
        self.approvals = 0
        self.rejected = False

    async def update(self, action: str, **data: Any) -> RunSnapshot:
        snapshot = await self.client.operation(self.id, self.claim_id, action, **data)
        if snapshot.status == "CANCELLED":
            raise RunCancelled("任务已取消。")
        return snapshot

    async def event(self, kind: str, text: str) -> None:
        await self.update("event", event={"kind": kind, "text": text[:16_000]})

    async def apply_patch(self, path: str, old_text: str, new_text: str) -> dict[str, str]:
        prepared = await asyncio.to_thread(self.changes.prepare, path, old_text, new_text)
        return await self._apply((prepared,), path)

    async def apply_patches(self, edits: list[dict[str, str]]) -> dict[str, Any]:
        prepared = await asyncio.to_thread(self.changes.prepare_many, edits)
        return await self._apply(prepared, f"{len(prepared)} 个文件")

    async def _apply(self, prepared: tuple[PreparedEdit, ...], label: str) -> dict[str, str]:
        if self.rejected or self.approvals >= MAX_APPROVALS:
            raise ValueError("用户已拒绝修改，或任务已达到审批轮数上限。")
        diff = "".join(edit.diff for edit in prepared)
        if len(diff) > MAX_DIFF:
            raise ValueError("diff 超过 Web 审批上限，请缩小修改范围。")
        approval_id = str(uuid4())
        snapshot = await self.update("preview", approval_id=approval_id, path=label, diff=diff)
        self.approvals += 1
        while snapshot.approval is not None and snapshot.approval.status == "pending":
            await asyncio.sleep(1)
            snapshot = await self.client.get(self.id)
        if snapshot.status == "CANCELLED":
            raise RunCancelled("任务已取消。")
        if snapshot.approval is None or snapshot.approval.status != "approved":
            self.rejected = True
            return {"status": "rejected", "path": label}

        grant = await self.update("begin_write", approval_id=approval_id)
        if (
            grant.status != "APPLYING"
            or grant.approval is None
            or str(grant.approval.id) != approval_id
        ):
            raise AgentError("服务未授予本地写入许可。")
        if grant.cancel_requested:
            await self.update("finish_write", approval_id=approval_id, error="写入前已取消。")
            raise RunCancelled("任务已取消。")
        try:
            if len(prepared) == 1:
                result = await asyncio.to_thread(self.changes.commit, prepared[0])
            else:
                change_id = await asyncio.to_thread(self.changes.commit_many, prepared)
                result = {"status": "applied", "path": label, "change_id": change_id}
        except (OSError, ValueError) as error:
            message = str(error) if isinstance(error, ValueError) else "本地写入失败。"
            await self.update("finish_write", approval_id=approval_id, error=message[:500])
            return {"error": message}
        # Retries start inside the HTTP operation, after the local commit has returned.
        await self.update("finish_write", approval_id=approval_id, change_id=result["change_id"])
        return result


class ReportedModel:
    def __init__(self, model: ChatModel, run: LocalRun) -> None:
        self.model = model
        self.run = run

    async def complete(
        self, messages: list[Message], tools: list[dict[str, Any]], on_text: Callable[[str], None]
    ) -> Message:
        reply = await self.model.complete(messages, tools, on_text)
        if reply.content.strip():
            await self.run.event("message", reply.content)
        return reply


class ReportedTools:
    def __init__(self, tools: WorkspaceTools, run: LocalRun) -> None:
        self.tools = tools
        self.run = run

    def definitions(self) -> list[dict[str, Any]]:
        return self.tools.definitions()

    async def call(self, tool_call: ToolCall) -> str:
        name = tool_call.name[:80]
        await self.run.event("tool_start", name)
        result = await self.tools.call(tool_call)
        payload = json.loads(result)
        error = payload.get("error")
        if error:
            await self.run.event("tool_error", f"{name} · {error}")
        elif name == "run_check":
            code = payload["exit_code"]
            outcome = "超时" if payload.get("timed_out") else f"退出码 {code}"
            detail = f"{payload['name']} · {outcome}\n{payload['output']}"
            await self.run.event("tool_end" if code == 0 else "tool_error", detail)
        elif payload.get("change_id"):
            await self.run.event("tool_end", f"{name} · 回退 ID {payload['change_id']}")
        else:
            await self.run.event("tool_end", name)
        return result


async def _watch_cancellation(run: LocalRun) -> None:
    while True:
        await asyncio.sleep(1)
        if (await run.client.get(run.id)).status == "CANCELLED":
            return


async def execute_local(
    run: LocalRun,
    model: ChatModel,
    tools: WorkspaceTools,
    task: str,
    max_steps: int,
    rules: str = "",
) -> None:
    async def work() -> None:
        await run_agent(
            ReportedModel(model, run),
            ReportedTools(tools, run),
            task,
            max_steps=max_steps,
            on_text=lambda _: None,
            on_tool=lambda _: None,
            edit=True,
            project_rules=rules,
            verify=tools.verification.feedback if tools.verification else None,
        )
        if tools.sources:
            sources = "\n".join(
                f"[{label}] {hit.citation.file_name} · 片段 {hit.citation.chunk_index + 1}"
                for label, hit in tools.sources.values()
            )
            await run.event("message", f"检索来源\n{sources}")
        await run.update("finish")

    agent = asyncio.create_task(work())
    watcher = asyncio.create_task(_watch_cancellation(run))
    try:
        done, _ = await asyncio.wait((agent, watcher), return_when=asyncio.FIRST_COMPLETED)
        if watcher in done:
            watcher.result()
        if agent in done:
            agent.result()
    except RunCancelled:
        pass
    except AgentError as error:
        try:
            await run.update("finish", error=str(error)[:500])
        except RunCancelled:
            pass
    finally:
        for task_future in (agent, watcher):
            task_future.cancel()
        await asyncio.gather(agent, watcher, return_exceptions=True)


async def serve(
    remote: ExecutorClient,
    executor_id: UUID,
    source: WorkspaceFiles,
    model: ChatModel,
    knowledge: KnowledgeClient,
    max_steps: int,
    commands: CommandMap,
) -> None:
    print(f"本地执行器 ID：{executor_id}", flush=True)
    while True:
        claim_id = uuid4()
        snapshot = await remote.claim(executor_id, claim_id)
        if snapshot is None:
            await asyncio.sleep(2)
            continue
        if snapshot.status == "RUNNING":
            print(f"已领取 Agent 任务 {snapshot.id}", flush=True)
            journal = journal_path()
            try:
                worktree = await asyncio.to_thread(
                    create_worktree, source, journal.parent, snapshot.id
                )
                rules = project_rules(worktree.files)
            except (AgentError, OSError, ValueError) as error:
                await remote.operation(snapshot.id, claim_id, "finish", error=str(error)[:500])
                continue
            print(f"隔离工作树：{worktree.files.root}", flush=True)
            changes = FileChanges(worktree.files, journal)
            run = LocalRun(remote, snapshot, claim_id, changes)
            tools = WorkspaceTools(
                knowledge,
                changes.files,
                run.apply_patch,
                apply_patches=run.apply_patches,
                verification=Verification(worktree.files.root, commands),
            )
            try:
                await run.event(
                    "message", f"工作树 {snapshot.id.hex} · 基线 {worktree.base_commit}"
                )
                await execute_local(run, model, tools, snapshot.task, max_steps, rules)
            except RunCancelled:
                pass

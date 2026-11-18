import asyncio
import logging
from typing import Any
from uuid import UUID, uuid4

import httpx
from pydantic import TypeAdapter

from app.api.dependencies import get_knowledge_search_service
from app.core.config import Settings
from app.core.errors import ApiError
from app.features.agent.checks import load_commands
from app.features.agent.cli import CliSettings
from app.features.agent.desktop import desktop_directory, desktop_file_request
from app.features.agent.edits import FileChanges, journal_path
from app.features.agent.executor import LocalRun, RunCancelled, execute_local, run_claimed
from app.features.agent.files import WorkspaceFiles
from app.features.agent.full_paths import FullAccessFiles, directory_request
from app.features.agent.local_store import LOCAL_EXECUTOR_ID, LOCAL_WORKSPACE_ID, LocalRunStore
from app.features.agent.model import ChatCompletionsModel
from app.features.agent.providers import connect_profile, http_url
from app.features.agent.runs import TERMINAL, AgentRuns, Claim, ExecutorOperation, RunSnapshot
from app.features.agent.runtime import AgentError, ChatModel, Message
from app.features.agent.tools import WorkspaceTools
from app.features.knowledge.schemas import KnowledgeSearchHit, KnowledgeSearchRequest

logger = logging.getLogger(__name__)
_operations = TypeAdapter(ExecutorOperation)


class LocalRunController:
    def __init__(self, runs: AgentRuns, workspace_id: UUID) -> None:
        self.runs = runs
        self.workspace_id = workspace_id

    async def get(self, run_id: UUID) -> RunSnapshot:
        row = await asyncio.to_thread(self.runs.get, self.workspace_id, run_id)
        return RunSnapshot.model_validate(row)

    async def operation(
        self, run_id: UUID, claim_id: UUID, action: str, **data: Any
    ) -> RunSnapshot:
        operation = _operations.validate_python(
            {
                "claim_id": claim_id,
                "op_id": uuid4(),
                "action": action,
                **data,
            }
        )
        row = await asyncio.to_thread(self.runs.execute, self.workspace_id, run_id, operation)
        return RunSnapshot.model_validate(row)


class LocalKnowledge:
    def __init__(self, workspace_id: UUID) -> None:
        self.workspace_id = workspace_id

    async def search(self, query: str, limit: int) -> list[KnowledgeSearchHit]:
        service = get_knowledge_search_service()
        response = await service.search(
            self.workspace_id, KnowledgeSearchRequest(query=query, limit=limit)
        )
        return response.hits[:limit]


def local_model(settings: Settings, client: httpx.AsyncClient) -> ChatModel:
    if settings.local_agent_model_config and settings.local_agent_profile:
        return connect_profile(
            client, settings.local_agent_model_config, settings.local_agent_profile
        )
    if settings.local_agent_model_config or settings.local_agent_profile:
        raise AgentError("本地模型档案须同时配置文件和名称。")
    base_url, api_key, model = CliSettings().model_connection()
    return ChatCompletionsModel(client, http_url(base_url, "模型服务"), api_key, model)


async def _standalone(
    settings: Settings,
    client: httpx.AsyncClient,
    controller: LocalRunController,
    snapshot: RunSnapshot,
    claim_id: UUID,
    store: LocalRunStore,
) -> None:
    assert settings.local_agent_root is not None
    desktop_request = desktop_file_request(snapshot.task)
    absolute_directory = directory_request(snapshot.task)
    if (
        desktop_request is not None or absolute_directory is not None
    ) and snapshot.permission != "full":
        raise AgentError("此目标位于项目目录之外。请将新任务的权限切换至「完全访问」。")

    root = settings.local_agent_root
    files = FullAccessFiles(root) if snapshot.permission == "full" else WorkspaceFiles(root)
    changes = FileChanges(files, journal_path())
    run = LocalRun(controller, snapshot, claim_id, changes)
    if desktop_request is not None:
        await run.create_desktop_file(
            desktop_request, desktop=WorkspaceFiles(desktop_directory(), allow_protected=True)
        )
        return
    if absolute_directory is not None:
        await run.event("tool_start", f"create_directory · {absolute_directory}")
        result = await run.create_directory(absolute_directory)
        await run.finish_creation("create_directory", result["path"], result)
        return

    history = []
    if snapshot.thread_id is not None:
        rows = await asyncio.to_thread(store.thread, snapshot.thread_id, 8)
        for row in rows:
            if row["created_at"] >= snapshot.created_at.isoformat() or row["status"] != "SUCCEEDED":
                continue
            replies = [event["text"] for event in row["events"] if event["kind"] == "message"]
            if replies:
                history.extend(
                    (Message("user", row["task"][:4000]), Message("assistant", replies[-1][:4000]))
                )
    context = tuple(history)
    model = local_model(settings, client)
    if snapshot.permission == "project":
        commands = load_commands(settings.local_agent_commands)
        await run_claimed(controller, snapshot, claim_id, files, model, None, 16, commands, context)
        return

    full = snapshot.permission == "full"
    tools = WorkspaceTools(
        None,
        files,
        run.apply_full_patch if full else None,
        create_file=run.create_file if full else None,
        create_directory=run.create_directory if full else None,
        full_access=full,
    )
    scope = (
        f"当前权限为完全访问。默认目录是 {files.root}，支持本机磁盘绝对路径。写入须等待用户审批。"
        "优先使用用户明确给出的路径。用户指定当前桌面时，使用「桌面/文件名」形式，由执行器解析实际桌面。"
        if full
        else f"当前权限为项目只读。读取范围为 {files.root}，不允许写入。"
    )
    await execute_local(
        run, model, tools, snapshot.task, 16, edit=full, scope=scope, history=context
    )


async def serve_local(settings: Settings, runs: AgentRuns) -> None:
    store = runs.store
    if not isinstance(store, LocalRunStore) or settings.local_agent_root is None:
        return
    workspace_filter = LOCAL_WORKSPACE_ID if settings.local_agent_token is not None else None
    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as client:
        while True:
            queued = await asyncio.to_thread(store.next_local, workspace_filter)
            if queued is None:
                await asyncio.sleep(0.4)
                continue
            workspace = UUID(queued["workspace_id"])
            claim_id = uuid4()
            claim = Claim(executor_id=LOCAL_EXECUTOR_ID, claim_id=claim_id)
            row = await asyncio.to_thread(runs.claim, workspace, claim)
            if row is None:
                await asyncio.sleep(0.4)
                continue
            controller = LocalRunController(runs, workspace)
            snapshot = RunSnapshot.model_validate(row)
            try:
                if workspace == LOCAL_WORKSPACE_ID:
                    await _standalone(settings, client, controller, snapshot, claim_id, store)
                    continue
                if (desktop_request := desktop_file_request(snapshot.task)) is not None:
                    changes = FileChanges(WorkspaceFiles(desktop_directory()), journal_path())
                    await LocalRun(controller, snapshot, claim_id, changes).create_desktop_file(
                        desktop_request
                    )
                    continue
                source = WorkspaceFiles(settings.local_agent_root)
                model = local_model(settings, client)
                commands = load_commands(settings.local_agent_commands)
                await run_claimed(
                    controller,
                    snapshot,
                    claim_id,
                    source,
                    model,
                    LocalKnowledge(workspace),
                    16,
                    commands,
                )
            except RunCancelled:
                continue
            except Exception as error:
                if isinstance(error, (AgentError, ApiError, OSError, ValueError)):
                    message = str(error)[:500]
                else:
                    logger.exception("Local Agent task failed")
                    message = "本地 Agent 执行失败，请查看服务日志。"
                current = await controller.get(snapshot.id)
                if current.status == "APPLYING" and current.approval:
                    current = await controller.operation(
                        snapshot.id,
                        claim_id,
                        "finish_write",
                        approval_id=current.approval.id,
                        error="本地执行中断，请检查目标文件。",
                    )
                if current.status not in TERMINAL:
                    await controller.operation(snapshot.id, claim_id, "finish", error=message)

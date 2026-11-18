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
from app.features.agent.executor import run_claimed
from app.features.agent.files import WorkspaceFiles
from app.features.agent.local_store import LOCAL_EXECUTOR_ID, LocalRunStore
from app.features.agent.model import ChatCompletionsModel
from app.features.agent.providers import connect_profile, http_url
from app.features.agent.runs import TERMINAL, AgentRuns, Claim, ExecutorOperation, RunSnapshot
from app.features.agent.runtime import AgentError, ChatModel
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


async def serve_local(settings: Settings, runs: AgentRuns) -> None:
    store = runs.store
    if not isinstance(store, LocalRunStore) or settings.local_agent_root is None:
        return
    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as client:
        while True:
            queued = await asyncio.to_thread(store.next_local)
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
                        error="本地执行中断，请检查工作树。",
                    )
                if current.status not in TERMINAL:
                    await controller.operation(snapshot.id, claim_id, "finish", error=message)

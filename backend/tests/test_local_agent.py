import json
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app import main
from app.api.auth import get_owned_workspace_id
from app.api.v1 import agent
from app.core.config import Settings
from app.core.errors import ApiError, register_error_handlers
from app.features.agent import local
from app.features.agent.local_store import LocalRunStore
from app.features.agent.run_store import SupabaseRunStore
from app.features.agent.runtime import Message, ToolCall


class FixtureModel:
    async def complete(self, messages, tools, on_text):
        if messages[-1].role == "user":
            data = '{"path":"README.md","old_text":"8000","new_text":"9000"}'
            return Message("assistant", "", (ToolCall("edit", "apply_patch", data),))
        assert json.loads(messages[-1].content)["status"] == "applied"
        return Message("assistant", "端口更新完毕。")


def _poll(http: TestClient, route: str, status: str) -> dict:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        snapshot = http.get(route).json()
        if snapshot["status"] == status:
            return snapshot
        assert snapshot["status"] not in {"FAILED", "CANCELLED"}, snapshot
        time.sleep(0.05)
    raise AssertionError(f"本地 Agent 未进入 {status}：{snapshot}")


def test_local_workbench_runs_without_remote_storage_or_executor_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    source_file = root / "README.md"
    source_file.write_bytes(b"port 8000\n")
    for args in (
        ["init", "--quiet"],
        ["config", "core.autocrlf", "false"],
        ["add", "."],
        [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.test",
            "commit",
            "-m",
            "test: 创建本机 Agent 验收仓库",
        ],
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    state = tmp_path / "state"
    workspace, task_id = uuid4(), uuid4()
    settings = Settings(local_agent_root=root)
    monkeypatch.setenv("KNOWTRACE_AGENT_STATE_DIR", str(state))
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(agent, "get_settings", lambda: settings)
    monkeypatch.setattr(local, "local_model", lambda *_: FixtureModel())
    monkeypatch.setattr(
        agent, "create_supabase_client", lambda *_: pytest.fail("本机任务无需 Supabase 数据表")
    )
    agent.get_agent_runs.cache_clear()
    app = FastAPI(lifespan=main.lifespan)
    register_error_handlers(app)
    app.include_router(agent.router)

    def owned(workspace_id: UUID) -> UUID:
        if workspace_id != workspace:
            raise ApiError(404, "WORKSPACE_NOT_FOUND", "未找到知识库。")
        return workspace_id

    app.dependency_overrides[get_owned_workspace_id] = owned
    base = f"/workspaces/{workspace}/agent/runs"
    route = f"{base}/{task_id}"
    try:
        with TestClient(app) as http:
            assert http.get(base + "/config").json() == {"mode": "local", "directory": "project"}
            assert http.get(base).json() == []
            created = http.post(base, json={"id": str(task_id), "task": "修改端口"})
            assert created.status_code == 201
            preview = _poll(http, route, "WAITING_APPROVAL")
            checkout = state / "worktrees" / task_id.hex / "README.md"
            assert "+port 9000" in preview["approval"]["diff"]
            assert checkout.read_bytes() == b"port 8000\n"
            decision = {"approval_id": preview["approval"]["id"], "approved": True}
            assert http.post(route + "/decision", json=decision).status_code == 200
            completed = _poll(http, route, "SUCCEEDED")
            assert completed["approval"]["change_id"]
            assert checkout.read_bytes() == b"port 9000\n"
            assert source_file.read_bytes() == b"port 8000\n"
            assert http.get(base.replace(str(workspace), str(uuid4()))).status_code == 404

        (db_path,) = state.glob("web-agent-*.sqlite3")
        saved = LocalRunStore(db_path).get(workspace, task_id)
        assert saved["approval"]["decision"] is True and saved["status"] == "SUCCEEDED"
        with TestClient(app) as http:
            assert http.get(route).json() == completed
    finally:
        agent.get_agent_runs.cache_clear()


def test_hosted_missing_agent_schema_has_actionable_error():
    query = MagicMock()
    query.table.return_value = query
    query.select.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.execute.side_effect = APIError({"code": "PGRST205", "message": "missing table"})
    with pytest.raises(ApiError) as caught:
        SupabaseRunStore(query).list(uuid4())
    assert caught.value.code == "AGENT_SCHEMA_UNAVAILABLE"
    assert caught.value.status_code == 503

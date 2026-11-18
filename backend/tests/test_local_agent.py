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
from app.api.v1 import agent, local_agent
from app.core.config import Settings
from app.core.errors import ApiError, register_error_handlers
from app.features.agent import local
from app.features.agent.desktop import desktop_file_request
from app.features.agent.edits import FileChanges
from app.features.agent.files import WorkspaceFiles
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


def _local_app(
    root: Path, state: Path, monkeypatch: pytest.MonkeyPatch, *, standalone: bool = False
) -> FastAPI:
    settings = Settings(
        local_agent_root=root, local_agent_token="test-local-token" if standalone else None
    )
    monkeypatch.setenv("KNOWTRACE_AGENT_STATE_DIR", str(state))
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(agent, "get_settings", lambda: settings)
    monkeypatch.setattr(local_agent, "get_settings", lambda: settings)
    monkeypatch.setattr(
        agent, "create_supabase_client", lambda *_: pytest.fail("本机任务无需 Supabase 数据表")
    )
    agent.get_agent_runs.cache_clear()
    app = FastAPI(lifespan=main.lifespan)
    register_error_handlers(app)
    app.include_router(agent.router)
    app.include_router(local_agent.router)
    return app


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
    monkeypatch.setattr(local, "local_model", lambda *_: FixtureModel())
    app = _local_app(root, state, monkeypatch)

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


@pytest.mark.parametrize(
    "outcome", ["approved", "rejected", "cancelled", "collision", "exists", "escape"]
)
def test_desktop_create_respects_approval_and_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    desktop = tmp_path / "redirected-desktop"
    desktop.mkdir()
    state = tmp_path / "state"
    monkeypatch.setattr(local, "desktop_directory", lambda: desktop)
    monkeypatch.setattr(local, "local_model", lambda *_: pytest.fail("精确文件任务无需模型"))
    app = _local_app(tmp_path, state, monkeypatch)
    workspace, task_id = uuid4(), uuid4()
    app.dependency_overrides[get_owned_workspace_id] = lambda: workspace
    base = f"/workspaces/{workspace}/agent/runs"
    route = f"{base}/{task_id}"
    name = "../123.txt" if outcome == "escape" else "123.txt"
    target = desktop / name
    if outcome == "exists":
        target.write_bytes(b"keep")

    try:
        with TestClient(app) as http:
            created = http.post(base, json={"id": str(task_id), "task": f"在桌面新建一个{name}"})
            assert created.status_code == 201
            if outcome == "exists":
                completed = _poll(http, route, "FAILED")
                assert completed["approval"] is None
                assert any("已存在" in event["text"] for event in completed["events"])
                assert target.read_bytes() == b"keep"
                return
            if outcome == "escape":
                completed = _poll(http, route, "FAILED")
                assert completed["approval"] is None
                assert not target.exists()
                return

            preview = _poll(http, route, "WAITING_APPROVAL")
            assert preview["approval"]["path"] == "桌面/123.txt"
            assert "新建空文件（0 字节）" in preview["approval"]["diff"]
            assert not target.exists()
            if outcome == "cancelled":
                assert http.post(route + "/cancel").status_code == 200
                _poll(http, route, "CANCELLED")
                assert not target.exists()
                return
            if outcome == "collision":
                target.write_text("keep", encoding="utf-8")
            decision = {
                "approval_id": preview["approval"]["id"],
                "approved": outcome != "rejected",
            }
            assert http.post(route + "/decision", json=decision).status_code == 200
            assert http.post(route + "/decision", json=decision).status_code == 200
            completed = _poll(http, route, "FAILED" if outcome == "collision" else "SUCCEEDED")
            if outcome == "collision":
                assert "已存在" in completed["approval"]["error"]
                assert target.read_text(encoding="utf-8") == "keep"
                return

        assert not (state / "worktrees").exists()
        with TestClient(app) as http:
            assert http.get(route).json() == completed
        if outcome == "approved":
            assert target.read_bytes() == b""
            changes = FileChanges(WorkspaceFiles(desktop), state / "changes.sqlite3")
            receipt = UUID(completed["approval"]["change_id"])
            assert not changes.undo(receipt, lambda _: False)
            assert target.exists()
            assert changes.undo(receipt, lambda diff: "删除由 Agent 新建的空文件" in diff)
        assert not target.exists()
    finally:
        agent.get_agent_runs.cache_clear()


@pytest.mark.parametrize(
    "task", ["不要在桌面新建123.txt", "在桌面创建快捷方式", "读取关于在桌面新建123.txt的说明"]
)
def test_desktop_request_requires_explicit_file_creation(task: str) -> None:
    assert desktop_file_request(task) is None


def test_desktop_undo_preserves_file_edited_after_preview(tmp_path: Path) -> None:
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    target = desktop / "123.txt"
    changes = FileChanges(WorkspaceFiles(desktop), tmp_path / "changes.sqlite3")
    receipt = UUID(changes.create_empty(target.name)["change_id"])

    def confirm(_: str) -> bool:
        target.write_bytes(b"keep")
        return True

    with pytest.raises(ValueError, match="已修改"):
        changes.undo(receipt, confirm)
    assert target.read_bytes() == b"keep"


def test_standalone_agent_enforces_permission_and_persists_followups(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "outside-project.txt"
    state = tmp_path / "state"

    class FilesystemModel:
        async def complete(self, messages, tools, on_text):
            names = {tool["function"]["name"] for tool in tools}
            assert "search_knowledge" not in names
            task = messages[-1]
            if task.role == "tool":
                assert json.loads(task.content)["status"] == "applied"
                return Message("assistant", "本机文件已写入。")
            if task.content == "只读检查":
                assert names == {"list_files", "read_file", "search_files"}
                return Message("assistant", "当前任务只读。")
            assert {"apply_patch", "create_file", "create_directory"} <= names
            arguments = {"path": str(external)}
            if task.content == "写入文件":
                return Message(
                    "assistant",
                    "",
                    (
                        ToolCall(
                            "create",
                            "create_file",
                            json.dumps({**arguments, "content": "original"}),
                        ),
                    ),
                )
            assert messages[1].content == "写入文件"
            assert messages[2].content == "本机文件已写入。"
            return Message(
                "assistant",
                "",
                (
                    ToolCall(
                        "patch",
                        "apply_patch",
                        json.dumps({**arguments, "old_text": "original", "new_text": "edited"}),
                    ),
                ),
            )

    monkeypatch.setattr(local, "local_model", lambda *_: FilesystemModel())
    app = _local_app(project, state, monkeypatch, standalone=True)
    root_route = "/agent/runs"
    headers = {"X-KnowTrace-Local": "test-local-token"}
    try:
        with TestClient(app) as http:
            assert http.get("/agent/threads").status_code == 403
            assert (
                http.get(
                    "/agent/threads", headers=headers | {"X-KnowTrace-Local": "wrong"}
                ).status_code
                == 403
            )
            http.headers.update(headers)
            readonly = str(uuid4())
            response = http.post(
                root_route,
                json={
                    "id": readonly,
                    "thread_id": readonly,
                    "task": "只读检查",
                    "permission": "read_only",
                },
            )
            assert response.status_code == 201
            assert _poll(http, f"{root_route}/{readonly}", "SUCCEEDED")["approval"] is None
            assert not external.exists()

            thread_id = str(uuid4())
            receipt = None
            for run_id, task, before, after in (
                (thread_id, "写入文件", None, b"original"),
                (str(uuid4()), "修改该文件", b"original", b"edited"),
            ):
                payload = {"id": run_id, "thread_id": thread_id, "task": task, "permission": "full"}
                route = f"{root_route}/{run_id}"
                assert http.post(root_route, json=payload).status_code == 201
                assert http.post(root_route, json=payload).json()["id"] == run_id
                assert (
                    http.post(root_route, json={**payload, "permission": "read_only"}).status_code
                    == 409
                )
                preview = _poll(http, route, "WAITING_APPROVAL")
                assert preview["approval"]["path"] == str(external)
                assert (external.read_bytes() if external.exists() else None) == before
                decision = {"approval_id": preview["approval"]["id"], "approved": True}
                assert http.post(route + "/decision", json=decision).status_code == 200
                complete = _poll(http, route, "SUCCEEDED")
                receipt = complete["approval"]["change_id"]
                assert external.read_bytes() == after

            assert not (state / "worktrees").exists()
            assert {x["id"] for x in http.get("/agent/threads").json()} == {readonly, thread_id}
        with TestClient(app, headers=headers) as http:
            turns = http.get(f"/agent/threads/{thread_id}").json()
            assert [row["task"] for row in turns] == ["写入文件", "修改该文件"]
            assert all(
                row["permission"] == "full" and row["status"] == "SUCCEEDED" for row in turns
            )
        changes = FileChanges(WorkspaceFiles(tmp_path), state / "changes.sqlite3")
        assert changes.undo(UUID(receipt), lambda _: True)
        assert external.read_bytes() == b"original"
    finally:
        agent.get_agent_runs.cache_clear()


def test_empty_directory_rollback_preserves_added_files(tmp_path):
    changes = FileChanges(WorkspaceFiles(tmp_path), tmp_path / "changes.sqlite3")
    assert "创建空文件夹" in changes.preview_entry("demo", None)
    receipt = UUID(changes.create_entry("demo", None)["change_id"])
    assert changes.undo(receipt, lambda diff: "空文件夹" in diff)
    assert not (tmp_path / "demo").exists()

    receipt = UUID(changes.create_entry("demo", None)["change_id"])
    target = tmp_path / "demo" / "preserve.txt"
    target.write_bytes(b"keep")
    with pytest.raises(ValueError, match="已修改"):
        changes.undo(receipt, lambda _: True)
    assert target.read_bytes() == b"keep"


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

import asyncio
import json
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.auth import get_owned_workspace_id
from app.api.v1.agent import get_agent_runs
from app.core.errors import ApiError
from app.features.agent.checks import load_commands
from app.features.agent.edits import FileChanges
from app.features.agent.executor import ExecutorClient, LocalRun, execute_local, serve
from app.features.agent.files import WorkspaceFiles
from app.features.agent.runs import AgentRuns, Claim, Row
from app.features.agent.runtime import Message, ToolCall
from app.features.agent.tools import KnowledgeClient, WorkspaceTools
from app.main import app

WORKSPACE = uuid4()
BASE = f"/api/v1/workspaces/{WORKSPACE}/agent/runs"
ACTIVE = {"RUNNING", "WAITING_APPROVAL", "APPLYING"}


class MemoryStore:
    def __init__(self) -> None:
        self.rows: dict[str, Row] = {}
        self.lock = Lock()

    def insert(self, data: Row) -> Row | None:
        with self.lock:
            if data["id"] in self.rows:
                return None
            row = {
                **data,
                "revision": 0,
                "created_at": datetime.now(UTC).isoformat(),
                "status": "QUEUED",
                "events": [],
                "approval": None,
                "claim_id": None,
                "executor_ops": [],
                "cancel_requested": False,
            }
            self.rows[row["id"]] = row
            return deepcopy(row)

    def list(self, workspace_id: UUID) -> list[Row]:
        with self.lock:
            return deepcopy(
                [row for row in self.rows.values() if row["workspace_id"] == str(workspace_id)]
            )

    def get(self, workspace_id: UUID, run_id: UUID) -> Row | None:
        return next((row for row in self.list(workspace_id) if row["id"] == str(run_id)), None)

    def claimed(self, workspace_id: UUID, claim: Claim) -> Row | None:
        return next(
            (
                row
                for row in self.list(workspace_id)
                if row["executor_id"] == str(claim.executor_id)
                and row["claim_id"] == str(claim.claim_id)
            ),
            None,
        )

    def queued(self, workspace_id: UUID, executor_id: UUID) -> Row | None:
        return next(
            (
                row
                for row in self.list(workspace_id)
                if row["executor_id"] == str(executor_id) and row["status"] == "QUEUED"
            ),
            None,
        )

    def update(self, row: Row, fields: Row) -> Row | None:
        with self.lock:
            current = self.rows[row["id"]]
            if current["revision"] != row["revision"]:
                return None
            if (
                fields.get("status") == "RUNNING"
                and current["status"] == "QUEUED"
                and any(
                    other["workspace_id"] == row["workspace_id"]
                    and other["executor_id"] == row["executor_id"]
                    and other["status"] in ACTIVE
                    for other in self.rows.values()
                )
            ):
                return None
            current.update(fields, revision=current["revision"] + 1)
            return deepcopy(current)


@pytest.fixture
def store() -> MemoryStore:
    memory = MemoryStore()
    app.dependency_overrides[get_agent_runs] = lambda: AgentRuns(memory)

    def owned(workspace_id: UUID) -> UUID:
        if workspace_id != WORKSPACE:
            raise ApiError(404, "WORKSPACE_NOT_FOUND", "未找到对应的知识库。")
        return workspace_id

    app.dependency_overrides[get_owned_workspace_id] = owned
    return memory


class PatchModel:
    def __init__(self) -> None:
        self.turn = 0

    async def complete(self, messages, tools, on_text) -> Message:
        self.turn += 1
        if self.turn == 1:
            return Message(
                "assistant", "", (ToolCall("read", "read_file", '{"path":"README.md"}'),)
            )
        if self.turn == 2:
            assert json.loads(messages[-1].content)["lines"] == ["port 8000"]
            patch = '{"path":"README.md","old_text":"port 8000","new_text":"port 9000"}'
            return Message("assistant", "", (ToolCall("edit", "apply_patch", patch),))
        assert json.loads(messages[-1].content)["status"] == "applied"
        return Message("assistant", "README 端口已改为 9000。")


class CountedChanges(FileChanges):
    writes = 0

    def commit(self, prepared):
        result = super().commit(prepared)
        self.writes += 1
        return result


async def _wait_for_preview(browser: httpx.AsyncClient, run_id: UUID) -> dict:
    async with asyncio.timeout(8):
        while True:
            current = (await browser.get(f"{BASE}/{run_id}")).json()
            if current["status"] == "WAITING_APPROVAL":
                return current
            await asyncio.sleep(0.025)


def test_resume_after_refresh_and_lost_write_responses(tmp_path: Path, store: MemoryStore) -> None:
    path = tmp_path / "README.md"
    path.write_bytes(b"port 8000\r\n")
    changes = CountedChanges(WorkspaceFiles(tmp_path), tmp_path / "state" / "changes.sqlite3")
    run_id, executor_id, claim_id = uuid4(), uuid4(), uuid4()
    transport = httpx.ASGITransport(app=app)
    lost: dict[str, dict] = {}

    async def disconnect_after_commit(request: httpx.Request) -> httpx.Response:
        response = await transport.handle_async_request(request)
        if request.url.path.endswith(("/executor", "/claim")):
            payload = json.loads(request.content)
            action = payload.get("action", "claim")
            if action in {"claim", "begin_write", "finish_write"} and action not in lost:
                assert response.is_success
                lost[action] = payload
                await response.aclose()
                raise httpx.ReadError(
                    "connection lost after the state was committed", request=request
                )
            if action in lost:
                assert lost[action] == payload
        return response

    async def test_flow() -> None:
        async with (
            httpx.AsyncClient(transport=transport, base_url="https://api.test") as browser,
            httpx.AsyncClient(transport=httpx.MockTransport(disconnect_after_commit)) as executor,
        ):
            body = {"id": str(run_id), "executor_id": str(executor_id), "task": "修改 README"}
            assert (await browser.post(BASE, json=body)).status_code == 201
            assert (await browser.post(BASE, json=body)).json()["revision"] == 0
            remote = ExecutorClient(executor, "https://api.test", WORKSPACE, "executor")
            claimed = await remote.claim(executor_id, claim_id)
            assert claimed is not None and claimed.id == run_id and claimed.status == "RUNNING"
            assert (
                await browser.post(
                    f"{BASE}/claim",
                    json={
                        "executor_id": str(executor_id),
                        "claim_id": str(uuid4()),
                    },
                )
            ).json() is None
            run = LocalRun(remote, claimed, claim_id, changes)
            knowledge = KnowledgeClient(executor, "https://api.test", WORKSPACE, "executor")
            tools = WorkspaceTools(knowledge, changes.files, run.apply_patch)
            agent = asyncio.create_task(execute_local(run, PatchModel(), tools, claimed.task, 5))
            pending = await _wait_for_preview(browser, run_id)
            assert path.read_bytes() == b"port 8000\r\n"
            assert pending["events"][-1] == {"kind": "tool_start", "text": "apply_patch"}
            assert "+port 9000" in pending["approval"]["diff"]

            await browser.aclose()
            # Re-open the browser connection while the local executor stays alive.
            async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as fresh:
                restored = (await fresh.get(f"{BASE}/{run_id}")).json()
                assert restored == pending
                assert (await fresh.get(BASE)).json()[0]["id"] == str(run_id)
                decision = {"approval_id": pending["approval"]["id"], "approved": True}
                approved = (await fresh.post(f"{BASE}/{run_id}/decision", json=decision)).json()
                assert approved["approval"]["decision"] is True
                assert (
                    await fresh.post(f"{BASE}/{run_id}/decision", json=decision)
                ).status_code == 200
                await asyncio.wait_for(agent, timeout=12)
                final = (await fresh.get(f"{BASE}/{run_id}")).json()
                assert final["status"] == "SUCCEEDED"
                assert final["approval"]["status"] == "applied"
                assert final["approval"]["change_id"]
                assert "claim_id" not in final and "executor_ops" not in final
                stream = await fresh.get(f"{BASE}/{run_id}/events?after={pending['revision']}")
                assert f"id: {final['revision']}" in stream.text
                assert '"status":"SUCCEEDED"' in stream.text
                replay = await fresh.get(f"{BASE}/{run_id}/events?after={final['revision']}")
                assert "event: snapshot" not in replay.text
                late = await fresh.post(f"{BASE}/{run_id}/executor", json=lost["begin_write"])
                assert late.json()["revision"] == final["revision"]
                assert set(lost) == {"claim", "begin_write", "finish_write"}
                assert path.read_bytes() == b"port 9000\r\n"
                assert changes.writes == 1

    asyncio.run(test_flow())


def test_worktree_runner_fixes_real_failure_across_code_config_and_docs(
    tmp_path: Path, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    state = tmp_path / "state"
    monkeypatch.setenv("KNOWTRACE_AGENT_STATE_DIR", str(state))
    monkeypatch.setenv("AGENT_API_KEY", "must-not-reach-checks")
    files = {
        "app.py": "def port():\n    return 8000\n",
        "config.json": '{"port": 8000}\n',
        "README.md": "Port: 8000\n",
        "AGENTS.md": "Keep deployment files synchronized.\n",
        "verify.py": (
            "import json, os, pathlib, sys\n"
            "from app import port\n"
            "check = sys.argv[1]\n"
            "assert 'AGENT_API_KEY' not in os.environ\n"
            "if check == 'build':\n"
            "    compile(pathlib.Path('app.py').read_text(), 'app.py', 'exec')\n"
            "elif check == 'lint':\n"
            "    for file in ('app.py', 'config.json', 'README.md'):\n"
            "        assert all(line == line.rstrip() "
            "for line in pathlib.Path(file).read_text().splitlines())\n"
            "else:\n"
            "    expected = json.loads(pathlib.Path('config.json').read_text())['port']\n"
            "    assert 'Port: ' + str(expected) in pathlib.Path('README.md').read_text()\n"
            "    if port() != expected:\n"
            "        sys.exit(f'port mismatch: expected {expected}, got {port()}')\n"
            "print(check + ' OK')\n"
        ),
    }
    for name, text in files.items():
        (source / name).write_bytes(text.encode())

    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", "-C", str(source), *args], stderr=subprocess.PIPE)

    git("init", "--quiet")
    git("add", ".")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.test",
        "commit",
        "-m",
        "test: 建立验证样例仓库",
    )
    (source / "app.py").write_bytes(b"private unstaged file\n")
    (source / "config.json").write_bytes(b"private staged file\n")
    git("add", "config.json")
    (source / "local.txt").write_bytes(b"untracked\n")
    original_status = git("status", "--porcelain")
    original_index = git("diff", "--cached", "--binary")
    manifest = tmp_path / "commands.json"
    manifest.write_text(
        json.dumps(
            {
                check: [sys.executable, "-B", "verify.py", check]
                for check in ("build", "lint", "test")
            }
        ),
        encoding="utf-8",
    )

    class IteratingModel:
        rounds = 0

        async def complete(self, messages, tools, on_text):
            self.rounds += 1
            assert "Keep deployment files synchronized." in messages[0].content
            turn = self.rounds
            if turn == 1:
                edits = [
                    {"path": "app.py", "old_text": "8000", "new_text": "9001"},
                    {"path": "config.json", "old_text": "8000", "new_text": "9000"},
                    {"path": "README.md", "old_text": "8000", "new_text": "9000"},
                ]
                call = ToolCall("batch", "apply_patches", json.dumps({"edits": edits}))
                return Message("assistant", "", (call,))
            if turn == 2:
                assert json.loads(messages[-1].content)["status"] == "applied"
                return Message("assistant", "", (ToolCall("test", "run_check", '{"name":"test"}'),))
            if turn == 3:
                result = json.loads(messages[-1].content)
                assert result["exit_code"] == 1
                assert "port mismatch: expected 9000, got 9001" in result["output"]
                patch = '{"path":"app.py","old_text":"9001","new_text":"9000"}'
                return Message("assistant", "", (ToolCall("fix", "apply_patch", patch),))
            if turn == 4:
                calls = tuple(
                    ToolCall(check, "run_check", json.dumps({"name": check}))
                    for check in ("test", "build", "lint")
                )
                return Message("assistant", "", calls)
            assert turn == 5
            for message in messages[-3:]:
                assert json.loads(message.content)["exit_code"] == 0
            return Message("assistant", "代码、配置和文档的端口已统一为 9000。")

    async def flow() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as http:
            run_id, executor_id = uuid4(), uuid4()
            response = await http.post(
                BASE,
                json={
                    "id": str(run_id),
                    "executor_id": str(executor_id),
                    "task": "将代码、配置和文档的端口统一为 9000，并验证。",
                },
            )
            assert response.status_code == 201
            remote = ExecutorClient(http, "https://api.test", WORKSPACE, "executor")
            knowledge = KnowledgeClient(http, "https://api.test", WORKSPACE, "executor")
            executor = asyncio.create_task(
                serve(
                    remote,
                    executor_id,
                    WorkspaceFiles(source),
                    IteratingModel(),
                    knowledge,
                    12,
                    load_commands(manifest),
                )
            )
            approvals = []
            try:
                async with asyncio.timeout(15):
                    while True:
                        if executor.done():
                            executor.result()
                        row = (await http.get(f"{BASE}/{run_id}")).json()
                        approval = row["approval"]
                        if (
                            approval
                            and approval["status"] == "pending"
                            and approval["id"] not in approvals
                        ):
                            approvals.append(approval["id"])
                            if len(approvals) == 1:
                                assert all(
                                    f"+++ b/{name}" in approval["diff"]
                                    for name in ("app.py", "config.json", "README.md")
                                )
                            else:
                                assert "-    return 9001" in approval["diff"]
                            confirmed = await http.post(
                                f"{BASE}/{run_id}/decision",
                                json={
                                    "approval_id": approval["id"],
                                    "approved": True,
                                },
                            )
                            assert confirmed.status_code == 200
                        if row["status"] in {"SUCCEEDED", "FAILED"}:
                            break
                        await asyncio.sleep(0.025)
                assert row["status"] == "SUCCEEDED", row
                assert len(approvals) == 2
                assert any(
                    "port mismatch: expected 9000, got 9001" in e["text"]
                    for e in row["events"]
                    if e["kind"] == "tool_error"
                )
                assert all(
                    any(f"{check} · 退出码 0" in e["text"] for e in row["events"])
                    for check in ("test", "build", "lint")
                )
                saved = store.get(WORKSPACE, run_id)
                assert saved["approval_history"][0]["id"] == approvals[0]
                worktree = state / "worktrees" / run_id.hex
                for name in ("app.py", "config.json", "README.md"):
                    assert "9000" in (worktree / name).read_text(encoding="utf-8")
                assert not (worktree / "local.txt").exists()
            finally:
                executor.cancel()
                await asyncio.gather(executor, return_exceptions=True)

    asyncio.run(flow())
    assert git("status", "--porcelain") == original_status
    assert git("diff", "--cached", "--binary") == original_index
    assert (source / "app.py").read_bytes() == b"private unstaged file\n"
    assert (source / "local.txt").read_bytes() == b"untracked\n"


@pytest.mark.parametrize("after_grant", [False, True])
def test_cancellation_respects_the_write_grant(store: MemoryStore, after_grant: bool) -> None:
    async def test_flow() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://api.test"
        ) as browser:
            run_id, executor_id, claim_id, approval_id = (str(uuid4()) for _ in range(4))
            route = f"{BASE}/{run_id}"
            await browser.post(
                BASE, json={"id": run_id, "executor_id": executor_id, "task": "编辑"}
            )
            await browser.post(
                f"{BASE}/claim", json={"executor_id": executor_id, "claim_id": claim_id}
            )

            async def execute(action: str, **payload):
                return await browser.post(
                    f"{route}/executor",
                    json={
                        "op_id": str(uuid4()),
                        "claim_id": claim_id,
                        "action": action,
                        **payload,
                    },
                )

            await execute("preview", approval_id=approval_id, path="README.md", diff="+new")
            decision = {"approval_id": approval_id, "approved": True}
            await browser.post(f"{route}/decision", json=decision)
            if after_grant:
                grant = await execute("begin_write", approval_id=approval_id)
                assert grant.json()["status"] == "APPLYING"
            cancelled = (await browser.post(f"{route}/cancel")).json()
            assert cancelled["cancel_requested"] is True
            assert cancelled["approval"]["decision"] is True
            if after_grant:
                assert cancelled["status"] == "APPLYING"
                change_id = str(uuid4())
                finished = await execute(
                    "finish_write", approval_id=approval_id, change_id=change_id
                )
                assert finished.json()["status"] == "CANCELLED"
                assert finished.json()["approval"]["change_id"] == change_id
            else:
                assert cancelled["status"] == "CANCELLED"
                assert cancelled["approval"]["status"] == "cancelled"
                assert (await execute("begin_write", approval_id=approval_id)).json() == cancelled
            assert (
                await browser.get(route.replace(str(WORKSPACE), str(uuid4())))
            ).status_code == 404

    asyncio.run(test_flow())

import asyncio
import json
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
from app.features.agent.edits import FileChanges
from app.features.agent.executor import ExecutorClient, LocalRun, execute_local
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

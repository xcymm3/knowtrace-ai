from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.features.agent.runs import Claim, Row

LOCAL_EXECUTOR_ID = UUID("7af3b161-7119-4818-b30a-57ae487c54cf")
LOCAL_WORKSPACE_ID = UUID("6ecddd9b-b5da-4dd5-954a-7283ebb66841")


class LocalRunStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    executor_id TEXT NOT NULL,
                    claim_id TEXT,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS agent_runs_list
                    ON agent_runs(workspace_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS agent_runs_queue
                    ON agent_runs(executor_id, status, created_at);
                CREATE UNIQUE INDEX IF NOT EXISTS agent_runs_claim
                    ON agent_runs(workspace_id, claim_id) WHERE claim_id IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS agent_runs_active
                    ON agent_runs(executor_id)
                    WHERE status IN ('RUNNING', 'WAITING_APPROVAL', 'APPLYING');
            """)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def exclusive_worker(self) -> Iterator[None]:
        with self.path.with_suffix(".lock").open("a+b") as lock:
            lock.seek(0)
            try:
                if os.name == "nt":
                    from msvcrt import LK_NBLCK, locking

                    locking(lock.fileno(), LK_NBLCK, 1)
                else:
                    from fcntl import LOCK_EX, LOCK_NB, flock

                    flock(lock.fileno(), LOCK_EX | LOCK_NB)
            except OSError as error:
                raise RuntimeError("此项目已有本地 Agent 执行器在运行。") from error
            yield

    def _select(self, suffix: str, *args: str) -> list[Row]:
        with self._connection() as db:
            return [
                json.loads(payload)
                for (payload,) in db.execute(f"SELECT payload FROM agent_runs {suffix}", args)
            ]

    def _first(self, suffix: str, *args: str) -> Row | None:
        rows = self._select(f"{suffix} LIMIT 1", *args)
        return rows[0] if rows else None

    def insert(self, data: Row) -> Row | None:
        row = {
            **data,
            "status": "QUEUED",
            "revision": 0,
            "created_at": datetime.now(UTC).isoformat(),
            "claim_id": None,
            "events": [],
            "approval": None,
            "approval_history": [],
            "cancel_requested": False,
            "executor_ops": [],
        }
        with self._connection() as db:
            inserted = db.execute(
                """INSERT INTO agent_runs VALUES (?, ?, ?, NULL, 'QUEUED', 0, ?, ?)
                   ON CONFLICT(id) DO NOTHING""",
                (
                    row["id"],
                    row["workspace_id"],
                    row["executor_id"],
                    row["created_at"],
                    json.dumps(row),
                ),
            )
        return row if inserted.rowcount else None

    def list(self, workspace_id: UUID) -> list[Row]:
        return self._select(
            "WHERE workspace_id = ? ORDER BY created_at DESC LIMIT 30", str(workspace_id)
        )

    def get(self, workspace_id: UUID, run_id: UUID) -> Row | None:
        return self._first("WHERE workspace_id = ? AND id = ?", str(workspace_id), str(run_id))

    def thread(self, thread_id: UUID, limit: int = 60) -> list[Row]:
        rows = self._select(
            "WHERE workspace_id = ? AND json_extract(payload, '$.thread_id') = ? "
            "ORDER BY created_at DESC LIMIT ?",
            str(LOCAL_WORKSPACE_ID),
            str(thread_id),
            str(limit),
        )
        return list(reversed(rows))

    def threads(self) -> list[Row]:
        return self._select(
            "WHERE workspace_id = ? AND id = json_extract(payload, '$.thread_id') "
            "ORDER BY created_at DESC LIMIT 100",
            str(LOCAL_WORKSPACE_ID),
        )

    def claimed(self, workspace_id: UUID, claim: Claim) -> Row | None:
        return self._first(
            "WHERE workspace_id = ? AND executor_id = ? AND claim_id = ?",
            str(workspace_id),
            str(claim.executor_id),
            str(claim.claim_id),
        )

    def queued(self, workspace_id: UUID, executor_id: UUID) -> Row | None:
        return self._first(
            "WHERE workspace_id = ? AND executor_id = ? AND status = 'QUEUED' ORDER BY created_at",
            str(workspace_id),
            str(executor_id),
        )

    def next_local(self, workspace: UUID | None = None) -> Row | None:
        where = "WHERE executor_id = ? AND status = 'QUEUED'"
        params = [str(LOCAL_EXECUTOR_ID)]
        if workspace is not None:
            where += " AND workspace_id = ?"
            params.append(str(workspace))
        return self._first(f"{where} ORDER BY created_at", *params)

    def update(self, row: Row, fields: Row) -> Row | None:
        current = {**row, **fields, "revision": row["revision"] + 1}
        try:
            with self._connection() as db:
                result = db.execute(
                    """UPDATE agent_runs SET claim_id = ?, status = ?, revision = ?, payload = ?
                       WHERE workspace_id = ? AND id = ? AND revision = ?""",
                    (
                        current["claim_id"],
                        current["status"],
                        current["revision"],
                        json.dumps(current),
                        row["workspace_id"],
                        row["id"],
                        row["revision"],
                    ),
                )
        except sqlite3.IntegrityError:
            return None
        return current if result.rowcount else None

    def interrupt_active(self) -> None:
        rows = self._select("WHERE status IN ('RUNNING', 'WAITING_APPROVAL', 'APPLYING')")
        for row in rows:
            message = "本地服务已重启。请检查该任务的目标文件，再发起新任务。"
            changes = {
                "status": "FAILED",
                "events": [
                    *row["events"],
                    {"kind": "error", "text": message},
                ],
            }
            approval = row["approval"]
            if approval and approval["status"] in {"pending", "approved", "applying"}:
                changes["approval"] = {**approval, "status": "failed", "error": message}
            self.update(row, changes)

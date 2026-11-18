import asyncio
import sys
from pathlib import Path
from uuid import UUID

import pytest

from app.features.agent.checks import Verification
from app.features.agent.edits import FileChanges
from app.features.agent.files import WorkspaceFiles


def test_batch_conflict_and_undo_preserve_complete_file_versions(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    root.mkdir()
    first = root / "one.txt"
    second = root / "two.txt"
    first.write_bytes(b"old one\r\n")
    second.write_bytes(b"old two\n")
    changes = FileChanges(WorkspaceFiles(root), tmp_path / "changes.sqlite3")
    with pytest.raises(ValueError, match="two.txt：原文不匹配"):
        changes.prepare_many(
            [
                {"path": "one.txt", "old_text": "old", "new_text": "new"},
                {"path": "two.txt", "old_text": "wrong", "new_text": "new"},
            ]
        )
    prepared = changes.prepare_many(
        [{"path": path.name, "old_text": "old", "new_text": "new"} for path in (first, second)]
    )

    second.write_bytes(b"human change\n")
    with pytest.raises(ValueError, match="预览后已变化"):
        changes.commit_many(prepared)
    assert first.read_bytes() == b"old one\r\n"
    assert second.read_bytes() == b"human change\n"

    second.write_bytes(b"old two\n")
    change_id = UUID(changes.commit_many(prepared))
    assert first.read_bytes() == b"new one\r\n"
    assert second.read_bytes() == b"new two\n"
    assert changes.undo(change_id, lambda diff: "-new one" in diff and "-new two" in diff)
    assert first.read_bytes() == b"old one\r\n"
    assert second.read_bytes() == b"old two\n"


def test_checks_limit_execution_to_named_commands_and_time_out(tmp_path: Path) -> None:
    verification = Verification(
        tmp_path,
        {"slow": (sys.executable, "-u", "-c", "import time; print('started'); time.sleep(15)")},
        timeout=1,
    )

    async def check() -> None:
        with pytest.raises(ValueError, match="未授权"):
            await verification.run("other")
        result = await verification.run("slow")
        assert result["timed_out"] is True
        assert result["exit_code"] is None
        assert "started" in result["output"]
        assert verification.feedback()

    asyncio.run(check())

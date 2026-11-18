import os
import re
import sqlite3
import stat
from bisect import bisect_left
from codecs import BOM_UTF8
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from difflib import unified_diff
from hashlib import sha256
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4

from app.features.agent.files import MAX_TEXT_BYTES, TextFile, WorkspaceFiles


def journal_path() -> Path:
    override = os.environ.get("KNOWTRACE_AGENT_STATE_DIR")
    if override:
        return Path(override) / "changes.sqlite3"
    if os.name == "nt" and (local := os.environ.get("LOCALAPPDATA")):
        return Path(local) / "KnowTrace" / "agent" / "changes.sqlite3"
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return state / "knowtrace" / "agent" / "changes.sqlite3"


def _changed_bytes(original: TextFile, old_text: str, new_text: str) -> bytes:
    old = old_text.replace("\r\n", "\n")
    new = new_text.replace("\r\n", "\n")
    if not old or "\x00" in new or "\r" in new:
        raise ValueError("补丁须提供原文，并使用普通 UTF-8 文本和换行。")

    normalized = original.text.replace("\r\n", "\n")
    start = normalized.find(old)
    if start < 0:
        raise ValueError("原文不匹配，请重新读取文件。")
    if normalized.find(old, start + 1) >= 0:
        raise ValueError("原文有多处匹配，请提供更多上下文。")

    # Map the model's LF offsets back to the original text without touching surrounding lines.
    crlf_offsets = [
        match.start() - index for index, match in enumerate(re.finditer("\r\n", original.text))
    ]
    end = start + len(old)
    start += bisect_left(crlf_offsets, start)
    end += bisect_left(crlf_offsets, end)
    matched_text = original.text[start:end]
    first_line = original.text.partition("\n")[0]
    if "\r\n" in matched_text or ("\n" not in matched_text and first_line.endswith("\r")):
        new = new.replace("\n", "\r\n")
    updated = original.text[:start] + new + original.text[end:]
    data = updated.encode("utf-8-sig" if original.data.startswith(BOM_UTF8) else "utf-8")
    if len(data) > MAX_TEXT_BYTES:
        raise ValueError("修改后的文件超过 256 KiB。")
    if data == original.data:
        raise ValueError("补丁没有变更。")
    return data


def _preview(path: str, before: bytes, after: bytes) -> str:
    diff = unified_diff(
        list(StringIO(before.decode("utf-8-sig"), newline="\n")),
        list(StringIO(after.decode("utf-8-sig"), newline="\n")),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    lines = []
    for line in diff:
        if line.endswith("\r\n"):
            line = line[:-2] + "\n"
        lines.append(
            "".join(
                char if char in "\n\t" or char.isprintable() else ascii(char)[1:-1] for char in line
            )
        )
        if not line.endswith("\n"):
            lines.append("\n\\ No newline at end of file\n")
    return "".join(lines)


@dataclass(frozen=True)
class PreparedEdit:
    path: str
    original: TextFile
    data: bytes
    diff: str


class IncompleteRestore(ValueError):
    pass


class FileChanges:
    def __init__(self, files: WorkspaceFiles, journal: Path) -> None:
        self.files = files
        self._journal = journal
        self._root_key = os.path.normcase(str(files.root))

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        try:
            self._journal.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with closing(sqlite3.connect(self._journal)) as db:
                with db:
                    db.execute(
                        """CREATE TABLE IF NOT EXISTS changes (
                            id TEXT PRIMARY KEY, root TEXT NOT NULL, path TEXT NOT NULL,
                            before_data BLOB NOT NULL, after_hash TEXT NOT NULL
                        )"""
                    )
                    db.execute(
                        """CREATE TABLE IF NOT EXISTS change_parts (
                            id TEXT NOT NULL, root TEXT NOT NULL, path TEXT NOT NULL,
                            before_data BLOB NOT NULL, after_hash TEXT NOT NULL,
                            PRIMARY KEY (id, path)
                        )"""
                    )
                yield db
        except sqlite3.Error as error:
            raise ValueError("无法读取或保存本地回退记录。") from error

    def _check_version(self, path: str, expected: TextFile) -> None:
        try:
            current = self.files.read_text_file(path)
        except (OSError, ValueError) as error:
            raise ValueError("文件在预览后已变化或无法访问，操作已取消。") from error
        if current.path != expected.path or current.data != expected.data:
            raise ValueError("文件在预览后已变化，操作已取消。")

    def _replace(self, path: str, expected: TextFile, data: bytes) -> None:
        self._check_version(path, expected)
        mode = stat.S_IMODE(expected.path.lstat().st_mode)
        if os.name == "nt" and not mode & stat.S_IWRITE:
            raise ValueError("目标文件为只读，无法写入。")
        temp_path: Path | None = None
        try:
            with NamedTemporaryFile(
                dir=expected.path.parent, prefix=".knowtrace-edit-", delete=False
            ) as target:
                temp_path = Path(target.name)
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            temp_path.chmod(mode)
            self._check_version(path, expected)
            temp_path.replace(expected.path)
            temp_path = None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def prepare(self, path: str, old_text: str, new_text: str) -> PreparedEdit:
        original = self.files.read_text_file(path)
        relative = original.path.relative_to(self.files.root).as_posix()
        data = _changed_bytes(original, old_text, new_text)
        return PreparedEdit(relative, original, data, _preview(relative, original.data, data))

    def prepare_many(self, edits: list[dict[str, str]]) -> tuple[PreparedEdit, ...]:
        prepared = []
        for edit in edits:
            try:
                prepared.append(self.prepare(**edit))
            except ValueError as error:
                raise ValueError(f"{edit['path']}：{error}") from error
        if not prepared or len({edit.original.path for edit in prepared}) != len(prepared):
            raise ValueError("每个补丁批次须包含文件，每个文件只能出现一次。")
        return tuple(prepared)

    def apply(
        self, path: str, old_text: str, new_text: str, confirm: Callable[[str], bool]
    ) -> dict[str, str]:
        prepared = self.prepare(path, old_text, new_text)
        if not confirm(prepared.diff):
            return {"status": "rejected", "path": prepared.path}
        return self.commit(prepared)

    def commit(self, prepared: PreparedEdit) -> dict[str, str]:
        return {
            "status": "applied",
            "path": prepared.path,
            "change_id": self.commit_many((prepared,)),
        }

    def _replace_all(self, edits: Sequence[PreparedEdit]) -> None:
        for edit in edits:
            self._check_version(edit.path, edit.original)
        applied: list[PreparedEdit] = []
        try:
            for edit in edits:
                self._replace(edit.path, edit.original, edit.data)
                applied.append(edit)
        except (OSError, ValueError) as error:
            restore_failed = []
            for edit in reversed(applied):
                try:
                    changed = TextFile(edit.original.path, edit.data, "")
                    self._replace(edit.path, changed, edit.original.data)
                except (OSError, ValueError):
                    restore_failed.append(edit.path)
            if restore_failed:
                raise IncompleteRestore(
                    f"部分文件在失败后未能还原：{', '.join(restore_failed)}"
                ) from error
            raise

    def commit_many(self, prepared: Sequence[PreparedEdit]) -> str:
        for edit in prepared:
            self._check_version(edit.path, edit.original)
        change_id = uuid4().hex
        with self._connect() as db:
            # Persist the original bytes before replacing the working file.
            with db:
                db.executemany(
                    "INSERT INTO change_parts VALUES (?, ?, ?, ?, ?)",
                    [
                        (
                            change_id,
                            self._root_key,
                            edit.path,
                            edit.original.data,
                            sha256(edit.data).hexdigest(),
                        )
                        for edit in prepared
                    ],
                )
            try:
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    self._replace_all(prepared)
            except IncompleteRestore as error:
                raise ValueError(f"{error}。原始内容已保存，记录 ID {change_id}。") from error
            except (OSError, ValueError):
                with db:
                    db.execute("DELETE FROM change_parts WHERE id = ?", (change_id,))
                raise
        return change_id

    def undo(self, change_id: UUID, confirm: Callable[[str], bool]) -> bool:
        if not self._journal.is_file():
            raise ValueError("当前目录没有对应的回退记录。")
        with self._connect() as db:
            rows = (
                db.execute(
                    "SELECT path, before_data, after_hash FROM change_parts "
                    "WHERE id = ? AND root = ?",
                    (change_id.hex, self._root_key),
                ).fetchall()
                or db.execute(
                    "SELECT path, before_data, after_hash FROM changes WHERE id = ? AND root = ?",
                    (change_id.hex, self._root_key),
                ).fetchall()
            )
            if not rows:
                raise ValueError("当前目录没有对应的回退记录。")
            prepared = []
            for path, original, after_hash in rows:
                current = self.files.read_text_file(path)
                if current.data == original:
                    continue
                if sha256(current.data).hexdigest() != after_hash:
                    raise ValueError(f"{path} 当前版本与该次 Agent 修改不一致，无法回退。")
                prepared.append(
                    PreparedEdit(path, current, original, _preview(path, current.data, original))
                )
            if not prepared:
                raise ValueError("这些文件已经是修改前的版本。")
            if not confirm("".join(edit.diff for edit in prepared)):
                return False
            with db:
                db.execute("BEGIN IMMEDIATE")
                self._replace_all(prepared)
        return True

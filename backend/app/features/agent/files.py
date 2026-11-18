import stat
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from itertools import islice
from pathlib import Path, PureWindowsPath
from typing import Any

_SKIPPED_NAMES = frozenset(
    {
        ".git",
        ".next",
        ".next-stale",
        ".ssh",
        ".aws",
        ".codex",
        ".agents",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        ".venv",
        ".npmrc",
        ".netrc",
        "credentials.json",
        "id_rsa",
        "id_ed25519",
    }
)
_KEY_SUFFIXES = (".pem", ".key", ".pfx", ".p12")
MAX_TEXT_BYTES = 256 * 1024
_SEARCH_FILES = 1000
_LINE_CHARS = 320


def _excluded(name: str) -> bool:
    name = name.casefold()
    return (
        name in _SKIPPED_NAMES
        or name.startswith((".env.", ".venv-", ".knowtrace-edit-"))
        or name == ".env"
        or name.endswith(_KEY_SUFFIXES)
    )


def _path_parts(path: str, *, allow_protected: bool = False) -> tuple[str, ...]:
    windows_path = PureWindowsPath(path)
    if windows_path.anchor:
        raise ValueError("请使用相对于授权目录的路径。")
    parts = windows_path.parts
    if any(
        part == ".."
        or part.rstrip(" .") != part
        or PureWindowsPath(part).is_reserved()
        or any(character in '<>:"|?*' or ord(character) < 32 for character in part)
        or (not allow_protected and _excluded(part))
        for part in parts
    ):
        raise ValueError("路径超出授权范围或包含受保护的名称。")
    return parts


def _plain_mode(path: Path) -> int:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or (
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise ValueError("文件工具不跟随符号链接或目录联接。")
    return info.st_mode


def _excerpt(line: str) -> str:
    return line if len(line) <= _LINE_CHARS else line[:_LINE_CHARS] + "…"


@dataclass(frozen=True)
class TextFile:
    path: Path
    data: bytes
    text: str


class WorkspaceFiles:
    def __init__(self, root: Path, *, allow_protected: bool = False) -> None:
        self.root = root.resolve(strict=True)
        self.allow_protected = allow_protected
        if not self.root.is_dir():
            raise ValueError("授权路径必须是目录。")

    def _target(self, path: str, *, directory: bool) -> Path:
        target = self.root
        mode = _plain_mode(target)
        for part in self._parts(path):
            target /= part
            mode = _plain_mode(target)
        target = target.resolve(strict=True)
        if not target.is_relative_to(self.root):
            raise ValueError("路径超出授权范围。")
        self._parts(target.relative_to(self.root).as_posix())
        if directory and not stat.S_ISDIR(mode):
            raise ValueError("目标必须是目录。")
        if not directory and not stat.S_ISREG(mode):
            raise ValueError("目标必须是普通文件。")
        return target

    def _files(self, directory: str) -> Iterator[Path]:
        for base, directories, names in self._target(directory, directory=True).walk():
            directories[:] = sorted(
                name for name in directories if self._scannable(base / name, stat.S_ISDIR)
            )
            for name in sorted(names):
                file = base / name
                if self._scannable(file, stat.S_ISREG):
                    yield file.relative_to(self.root)

    def direct_file_path(self, name: str) -> Path:
        if self._parts(name) != (name,):
            raise ValueError("请只填写文件名，文件须直接位于授权目录中。")
        return self._target(".", directory=True) / name

    def entry_target(self, path: str) -> tuple["WorkspaceFiles", str]:
        parts = self._parts(path)
        if not parts:
            raise ValueError("请指定文件或文件夹的路径。")
        parent = self._target("/".join(parts[:-1]), directory=True)
        return WorkspaceFiles(parent, allow_protected=self.allow_protected), parts[-1]

    def _parts(self, path: str) -> tuple[str, ...]:
        return _path_parts(path, allow_protected=self.allow_protected)

    def _scannable(self, path: Path, type_check: Callable[[int], bool]) -> bool:
        try:
            self._parts(path.name)
            return type_check(_plain_mode(path))
        except (OSError, ValueError):
            return False

    def list_files(self, directory: str, limit: int) -> dict[str, Any]:
        files = list(islice(self._files(directory), limit + 1))
        return {
            "files": [file.as_posix() for file in files[:limit]],
            "truncated": len(files) > limit,
        }

    def read_text_file(self, path: str) -> TextFile:
        target = self._target(path, directory=False)
        with target.open("rb") as file:
            data = file.read(MAX_TEXT_BYTES + 1)
        if len(data) > MAX_TEXT_BYTES:
            raise ValueError("文件超过 256 KiB，请选择较小的文本文件。")
        if b"\x00" not in data:
            try:
                return TextFile(target, data, data.decode("utf-8-sig"))
            except UnicodeDecodeError:
                pass
        raise ValueError("文件工具仅支持 UTF-8 文本。")

    def _read_lines(self, path: str) -> list[str]:
        return self.read_text_file(path).text.splitlines()

    def read_file(self, path: str, start_line: int, line_count: int) -> dict[str, Any]:
        lines = self._read_lines(path)
        end_line = min(len(lines), start_line + line_count - 1)
        return {
            "path": "/".join(self._parts(path)),
            "start_line": start_line,
            "total_lines": len(lines),
            "lines": [_excerpt(line) for line in lines[start_line - 1 : end_line]],
            "next_line": end_line + 1 if end_line < len(lines) else None,
        }

    def search_files(self, query: str, directory: str, limit: int) -> dict[str, Any]:
        matches: list[dict[str, Any]] = []
        needle = query.casefold()
        for index, path in enumerate(islice(self._files(directory), _SEARCH_FILES + 1)):
            if index == _SEARCH_FILES:
                return {"matches": matches, "truncated": True}
            try:
                lines = self._read_lines(path.as_posix())
            except (OSError, ValueError):
                continue
            for number, line in enumerate(lines, start=1):
                if needle in line.casefold():
                    if len(matches) == limit:
                        return {"matches": matches, "truncated": True}
                    matches.append(
                        {
                            "path": path.as_posix(),
                            "line": number,
                            "excerpt": _excerpt(line),
                        }
                    )
        return {"matches": matches, "truncated": False}

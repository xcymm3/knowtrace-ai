import os
import re
from pathlib import Path
from typing import Any

from app.features.agent.files import WorkspaceFiles, _path_parts


class FullAccessFiles(WorkspaceFiles):
    def _local_path(self, value: str) -> Path:
        path = Path(value)
        if path.anchor and (
            not path.is_absolute()
            or (os.name == "nt" and not re.fullmatch(r"[A-Za-z]:\\", path.anchor))
        ):
            raise ValueError("请使用本机磁盘的完整路径，例如 D:\\项目\\文件.txt。")
        parts = path.parts[1:] if path.anchor else path.parts
        for part in parts:
            _path_parts(part, allow_protected=True)
        return path if path.is_absolute() else self.root / path

    def entry_target(self, path: str) -> tuple[WorkspaceFiles, str]:
        target = self._local_path(path)
        if target == Path(target.anchor) or not target.name:
            raise ValueError("请指定文件或子文件夹的路径。")
        files = WorkspaceFiles(target.parent, allow_protected=True)
        files.direct_file_path(target.name)
        return files, target.name

    def list_files(self, directory: str, limit: int) -> dict[str, Any]:
        files = WorkspaceFiles(self._local_path(directory), allow_protected=True)
        entries = []
        for index, path in enumerate(files.root.iterdir()):
            if index == limit:
                return {"entries": entries, "truncated": True}
            entries.append(str(path))
        return {"entries": entries, "truncated": False}

    def search_files(self, query: str, directory: str, limit: int) -> dict[str, Any]:
        files = WorkspaceFiles(self._local_path(directory), allow_protected=True)
        result = files.search_files(query, ".", limit)
        for entry in result["matches"]:
            entry["path"] = str(files.root / entry["path"])
        return result

    def read_file(self, path: str, start_line: int, line_count: int) -> dict[str, Any]:
        files, name = self.entry_target(path)
        result = files.read_file(name, start_line, line_count)
        result["path"] = str(files.root / name)
        return result


_MKDIR = re.compile(
    r"(?:请\s*)?(?:帮我\s*)?(?:在\s*)?([A-Za-z])\s*盘(?:根目录)?\s*"
    r"(?:新建|创建|建|建立)\s*(?:一个|个)?\s*(?:空)?文件夹"
    r"(?:\s*[,，]?\s*(?:名称为|名为|叫做|叫|命名为)?\s*(.*?)\s*)?[。！]?",
)
_MKDIR_PATH = re.compile(
    r"(?:请\s*)?(?:帮我\s*)?(?:新建|创建|建|建立)\s*(?:一个|个)?\s*(?:空)?文件夹\s*"
    r"""["“']?([A-Za-z]:[\\/][^\r\n]+?)["”']?[。！]?""",
)


def directory_request(task: str) -> str | None:
    if os.name != "nt":
        return None
    if match := _MKDIR.fullmatch(task):
        drive, name = match.groups()
        name = (name or "").strip().strip("\"“”'") or "新建文件夹"
        return f"{drive.upper()}:\\{name}"
    if match := _MKDIR_PATH.fullmatch(task):
        return match[1].strip()
    return None

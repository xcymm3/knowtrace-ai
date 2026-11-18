import ctypes
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

_CREATE = r"(?:创建|新建|建立|生成)\s*(?:一个\s*)?(?:(?:空)?文件\s*)?(?:名为\s*)?"
_DESKTOP = r"(?:我(?:的)?|本机(?:的)?)?桌面(?:上)?"
_NAME = r"""(?:"([^"]+)"|'([^']+)'|“([^”]+)”|([^\s。！？]+\.[\w-]+))"""
_REQUESTS = (
    re.compile(rf"(?:请\s*)?(?:帮我\s*)?在{_DESKTOP}\s*{_CREATE}{_NAME}(?:\s+(?:空)?文件)?[。！]?"),
    re.compile(
        rf"(?:请\s*)?(?:帮我\s*)?{_CREATE}{_NAME}(?:\s+(?:空)?文件)?\s*(?:到|在){_DESKTOP}[。！]?"
    ),
    re.compile(
        rf"(?:please\s+)?create\s+(?:an?\s+)?(?:empty\s+)?(?:file\s+(?:named\s+)?)?{_NAME}\s+on\s+(?:my|the)\s+desktop[.!]?",
        re.IGNORECASE,
    ),
)
_CONTENT_REQUEST = re.compile(
    r"(.+?)[,，;；]\s*(?:文件)?内容\s*(?:写(?:成|入)?|为|是|[:：])\s*[:：]?\s*(.+)",
    re.DOTALL,
)
_QUOTED_CONTENT = re.compile(
    r"""(?:"([^"]*)"|'([^']*)'|“([^”]*)”|‘([^’]*)’|「([^」]*)」|『([^』]*)』)[。！.!]?"""
)


@dataclass(frozen=True)
class DesktopFileRequest:
    name: str
    content: str = ""


def _desktop_name(task: str) -> str | None:
    for pattern in _REQUESTS:
        if match := pattern.fullmatch(task.strip()):
            return next(value for value in match.groups() if value is not None)
    return None


def desktop_file_request(task: str) -> DesktopFileRequest | None:
    if name := _desktop_name(task):
        return DesktopFileRequest(name)
    if suffix := _CONTENT_REQUEST.fullmatch(task.strip()):
        request, value = suffix.groups()
        name = _desktop_name(request)
        quoted = _QUOTED_CONTENT.fullmatch(value.strip())
        if name and quoted:
            content = next(text for text in quoted.groups() if text is not None)
            return DesktopFileRequest(name, content)
    return None


def desktop_directory() -> Path:
    if os.name != "nt":
        return Path.home() / "Desktop"

    # FOLDERID_Desktop also resolves Windows desktops redirected to OneDrive or another drive.
    folder = (ctypes.c_ubyte * 16).from_buffer_copy(
        UUID("B4BFCC3A-DB2C-424C-B029-7FE99A87C641").bytes_le
    )
    location = ctypes.c_wchar_p()
    try:
        result = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(folder), 0, None, ctypes.byref(location)
        )
        if result != 0 or not location.value:
            raise ValueError("Windows 无法定位当前用户的桌面目录。")
        return Path(location.value)
    finally:
        if location:
            ctypes.windll.ole32.CoTaskMemFree(location)

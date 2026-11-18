import asyncio
import os
import re
import shutil
import signal
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from app.features.agent.runtime import AgentError

CommandMap = dict[str, tuple[str, ...]]
_OUTPUT_LIMIT = 12_000
_ENV = {
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "PATHEXT",
    "HOME",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
}


def command_environment() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if name.upper() in _ENV}


def load_commands(path: Path | None) -> CommandMap:
    if path is None:
        return {}
    try:
        with path.open("rb") as source:
            raw = source.read(32_769)
        if len(raw) > 32_768:
            raise ValueError("命令清单过大")
        data = TypeAdapter(dict[str, list[str]]).validate_json(raw)
        if not data or len(data) > 8:
            raise ValueError("命令清单须包含 1–8 条命令")
        commands: CommandMap = {}
        for name, args in data.items():
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", name) or not args or len(args) > 32:
                raise ValueError("命令名称或参数无效")
            if not all(arg and "\x00" not in arg for arg in args):
                raise ValueError("命令参数无效")
            executable = shutil.which(args[0])
            if not executable or (os.name == "nt" and Path(executable).suffix.lower() != ".exe"):
                raise ValueError(f"{name} 需要本机可执行程序，Windows 下须为 .exe")
            resolved = str(Path(executable).resolve(strict=True))
            commands[name] = (resolved, *args[1:])
        return commands
    except (OSError, ValidationError) as error:
        raise AgentError("无法读取本地验证命令清单。") from error
    except ValueError as error:
        raise AgentError(str(error)) from error


async def _stop(process: asyncio.subprocess.Process) -> None:
    if os.name == "nt":
        taskkill = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "taskkill.exe"
        try:
            stop = await asyncio.create_subprocess_exec(
                str(taskkill),
                "/T",
                "/F",
                "/PID",
                str(process.pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(stop.wait(), timeout=3)
            except TimeoutError:
                stop.kill()
        except OSError:
            pass
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(process.wait(), timeout=3)
    except TimeoutError:
        pass


class Verification:
    def __init__(self, root: Path, commands: CommandMap, timeout: float = 180) -> None:
        self.root = root
        self.commands = commands
        self.timeout = timeout
        self.results: dict[str, dict[str, Any]] = {}
        self.remaining = max(12, len(commands) * 2)

    def invalidate(self) -> None:
        self.results.clear()

    def feedback(self) -> str | None:
        incomplete = [
            name
            for name in self.commands
            if name not in self.results or self.results[name]["exit_code"] != 0
        ]
        return f"当前版本尚未通过这些验证：{', '.join(incomplete)}。" if incomplete else None

    async def run(self, name: str) -> dict[str, Any]:
        args = self.commands.get(name)
        if args is None:
            raise ValueError("命令未授权，请选择本机清单中列出的名称。")
        if self.remaining <= 0:
            raise ValueError("已用完本次任务的验证次数。")
        self.remaining -= 1
        env = command_environment()
        env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1", CI="true")
        options = {"start_new_session": True} if os.name != "nt" else {}
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=self.root,
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                **options,
            )
        except OSError:
            result = {"name": name, "exit_code": None, "output": "无法启动已授权的命令。"}
            self.results[name] = result
            return result
        assert process.stdout is not None
        output = bytearray()
        truncated = False
        timed_out = False
        try:
            async with asyncio.timeout(self.timeout):
                while chunk := await process.stdout.read(4096):
                    output.extend(chunk)
                    if len(output) > _OUTPUT_LIMIT:
                        del output[:-_OUTPUT_LIMIT]
                        truncated = True
                await process.wait()
        except TimeoutError:
            timed_out = True
            await _stop(process)
        except asyncio.CancelledError:
            await _stop(process)
            raise
        text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", output.decode("utf-8", "replace"))
        result = {
            "name": name,
            "exit_code": None if timed_out else process.returncode,
            "output": text,
            "timed_out": timed_out,
            "truncated": truncated,
        }
        self.results[name] = result
        return result

import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.features.agent.checks import command_environment
from app.features.agent.files import WorkspaceFiles
from app.features.agent.runtime import AgentError


@dataclass(frozen=True)
class GitWorktree:
    files: WorkspaceFiles
    base_commit: str


def project_rules(files: WorkspaceFiles) -> str:
    try:
        return files.read_text_file("AGENTS.md").text[:8000]
    except FileNotFoundError:
        return ""
    except (OSError, ValueError) as error:
        raise AgentError("无法读取工作树的 AGENTS.md。") from error


def create_worktree(source: WorkspaceFiles, state_dir: Path, run_id: UUID) -> GitWorktree:
    state = state_dir.resolve()
    if state.is_relative_to(source.root):
        raise AgentError("工作树状态目录必须位于原仓库之外。")

    def git(*args: str) -> str:
        env = command_environment()
        env["GIT_TERMINAL_PROMPT"] = "0"
        try:
            return (
                subprocess.run(
                    [
                        "git",
                        "-c",
                        f"core.hooksPath={state / 'empty-hooks'}",
                        "-c",
                        "core.fsmonitor=false",
                        "-C",
                        str(source.root),
                        *args,
                    ],
                    env=env,
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
                .stdout.decode("utf-8")
                .strip()
            )
        except (OSError, subprocess.SubprocessError, UnicodeError) as error:
            raise AgentError(
                "无法从当前 Git HEAD 创建隔离工作树，请检查仓库和本地权限。"
            ) from error

    if Path(git("rev-parse", "--show-toplevel")).resolve() != source.root:
        raise AgentError("隔离模式的 --root 必须是 Git 仓库根目录。")
    base = git("rev-parse", "--verify", "HEAD^{commit}")
    # Claim IDs select tasks. A pre-existing directory must never be reused as a worktree.
    root = state / "worktrees" / run_id.hex
    if root.exists() or root.is_symlink():
        raise AgentError("该任务的工作树已存在，请在本地查看现有结果。")
    root.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if root.parent.resolve() != root.parent:
        raise AgentError("工作树目录不能通过链接重定向。")
    git("worktree", "add", "--detach", str(root), base)
    return GitWorktree(WorkspaceFiles(root), base)

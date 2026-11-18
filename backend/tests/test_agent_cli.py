import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app.api.auth import get_owned_workspace_id
from app.api.dependencies import get_knowledge_search_service
from app.features.agent.cli import main
from app.features.agent.files import WorkspaceFiles
from app.features.knowledge.service import KnowledgeSearchService
from app.main import app

WORKSPACE_ID = UUID("c23e4e41-ddbd-4cdd-9ba1-9c53f4313ad7")
CHUNK_ID = "c6d3472e-7008-49f0-bafd-b07906319239"


def _sse(*frames: tuple[dict, str | None], done: bool = True) -> httpx.Response:
    body = "".join(
        f"data: {json.dumps({'choices': [{'delta': delta, 'finish_reason': finish}]})}\n\n"
        for delta, finish in frames
    )
    return httpx.Response(
        200,
        text=body + ("data: [DONE]\n\n" if done else ""),
        headers={"Content-Type": "text/event-stream"},
    )


def _tool(name: str, call_id: str, arguments: str = "", index: int = 0) -> dict:
    return {
        "id": call_id,
        "index": index,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


class _Embeddings:
    async def embed(self, inputs: list[str]) -> list[list[float]]:
        assert inputs == ["启动端口"]
        return [[0.1]]


class _KnowledgeStore:
    def search(self, workspace_id, vector, query, limit, document_kind) -> list[dict]:
        assert (workspace_id, vector, query, limit, document_kind) == (
            WORKSPACE_ID,
            [0.1],
            "启动端口",
            6,
            None,
        )
        return [
            {
                "id": CHUNK_ID,
                "document_id": "0424ca08-7828-4568-9042-e136b7850909",
                "content": "部署服务应监听 9000 端口。",
                "file_name": "部署说明.md",
                "kind": "REFERENCE",
                "metadata": {"chunkIndex": 3},
            }
        ]


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    provider: Callable[[httpx.Request], httpx.Response],
) -> None:
    original_client = httpx.AsyncClient
    rag = httpx.ASGITransport(app=app)

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "knowtrace.test":
            assert request.method == "POST"
            assert request.url.path == f"/api/v1/workspaces/{WORKSPACE_ID}/search"
            assert request.headers["Authorization"] == "Bearer fake-user-token"
            return await rag.handle_async_request(request)
        assert request.url == "https://deepseek.test/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer fake-provider-key"
        return provider(request)

    monkeypatch.setenv("AGENT_API_KEY", "fake-provider-key")
    monkeypatch.setenv("AGENT_BASE_URL", "https://deepseek.test/v1")
    monkeypatch.setenv("AGENT_MODEL", "deepseek-test")
    monkeypatch.setenv("KNOWTRACE_ACCESS_TOKEN", "fake-user-token")
    monkeypatch.setenv("KNOWTRACE_API_BASE_URL", "https://knowtrace.test/api/v1/")
    monkeypatch.setattr(
        "app.features.agent.cli.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs),
    )


def _argv(root: Path, max_steps: int = 8) -> list[str]:
    return [
        "--root",
        str(root),
        "--workspace-id",
        str(WORKSPACE_ID),
        "--max-steps",
        str(max_steps),
        "检查 README 的部署步骤",
    ]


def test_cli_uses_knowledge_and_local_files_with_deepseek_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# 示例\n启动端口 8000\n", encoding="utf-8")
    before = readme.read_bytes()
    service = KnowledgeSearchService(_KnowledgeStore(), _Embeddings())
    app.dependency_overrides[get_knowledge_search_service] = lambda: service

    async def owned_workspace(workspace_id: UUID) -> UUID:
        assert workspace_id == WORKSPACE_ID
        return workspace_id

    app.dependency_overrides[get_owned_workspace_id] = owned_workspace
    requests = []

    def provider(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-test"
        assert payload["stream"] is True
        assert {item["function"]["name"] for item in payload["tools"]} == {
            "search_knowledge",
            "list_files",
            "search_files",
            "read_file",
        }
        requests.append(payload)
        messages = payload["messages"]
        if len(requests) == 1:
            return _sse(
                ({"reasoning_content": "provider "}, None),
                ({"reasoning_content": "state"}, None),
                ({"tool_calls": [_tool("search_knowledge", "knowledge", '{"query":')]}, None),
                (
                    {"tool_calls": [{"index": 0, "function": {"arguments": '"启动端口"}'}}]},
                    "tool_calls",
                ),
            )
        assert messages[2]["reasoning_content"] == "provider state"
        assert messages[3]["tool_call_id"] == "knowledge"
        hit = json.loads(messages[3]["content"])["matches"][0]
        assert hit["source"] == "K1"
        assert hit["chunk_id"] == CHUNK_ID
        if len(requests) == 2:
            return _sse(
                (
                    {
                        "tool_calls": [
                            _tool("search_files", "search", '{"query":"启动端口"}', index=1),
                            _tool("list_files", "list", "{}"),
                        ]
                    },
                    "tool_calls",
                ),
            )
        assert [item["tool_call_id"] for item in messages[5:7]] == ["list", "search"]
        result = json.loads(messages[6]["content"])["matches"][0]
        assert result == {"path": "README.md", "line": 2, "excerpt": "启动端口 8000"}
        if len(requests) == 3:
            return _sse(
                (
                    {"tool_calls": [_tool("read_file", "read", '{"path":"README.md"}')]},
                    "tool_calls",
                ),
            )
        assert json.loads(messages[-1]["content"])["lines"] == ["# 示例", "启动端口 8000"]
        return _sse(
            ({"content": "README.md:2 "}, None),
            ({"content": "应使用 9000 [K1]。"}, "stop"),
        )

    _configure(monkeypatch, provider)
    assert main(_argv(tmp_path)) == 0
    stdout, stderr = capsys.readouterr()
    assert "README.md:2 应使用 9000 [K1]。" in stdout
    assert f"[K1] 部署说明.md · 片段 4 · {CHUNK_ID}" in stdout
    assert "[工具] read_file" in stderr
    assert "provider state" not in stdout + stderr
    assert len(requests) == 4
    assert readme.read_bytes() == before


@pytest.mark.parametrize("done,max_steps", [(False, 8), (True, 1)])
def test_cli_stops_before_running_incomplete_or_over_budget_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    done: bool,
    max_steps: int,
) -> None:
    def provider(_: httpx.Request) -> httpx.Response:
        return _sse(
            ({"tool_calls": [_tool("read_file", "read", '{"path":"README.md"}')]}, "tool_calls"),
            done=done,
        )

    _configure(monkeypatch, provider)
    assert main(_argv(tmp_path, max_steps)) == 1
    _, stderr = capsys.readouterr()
    assert ("轮数" if done else "未正常完成") in stderr
    assert "[工具]" not in stderr


def test_file_tools_enforce_boundaries_and_paginate(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (tmp_path / "outside.txt").write_text("marker", encoding="utf-8")
    (root / ".env").write_text("marker", encoding="utf-8")
    (root / "binary.txt").write_bytes(b"marker\x00")
    (root / "项目.txt").write_text("第一行\nMarker 第二行\n第三行", encoding="utf-8-sig")
    files = WorkspaceFiles(root)

    assert files.list_files(".", 1) == {"files": ["binary.txt"], "truncated": True}
    assert files.search_files("marker", ".", 8)["matches"] == [
        {"path": "项目.txt", "line": 2, "excerpt": "Marker 第二行"}
    ]
    assert files.read_file("项目.txt", 2, 1) == {
        "path": "项目.txt",
        "start_line": 2,
        "total_lines": 3,
        "lines": ["Marker 第二行"],
        "next_line": 3,
    }
    for path in ("../outside.txt", str(tmp_path / "outside.txt"), ".env", "项目.txt:stream"):
        with pytest.raises(ValueError):
            files.read_file(path, 1, 1)
    with pytest.raises(ValueError, match="UTF-8"):
        files.read_file("binary.txt", 1, 1)


def _link(link: Path, target: Path) -> None:
    if os.name == "nt":
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$ErrorActionPreference = 'Stop'; "
                "New-Item -ItemType Junction -Path $env:KNOWTRACE_TEST_LINK "
                "-Target $env:KNOWTRACE_TEST_TARGET | Out-Null",
            ],
            env={
                **os.environ,
                "KNOWTRACE_TEST_LINK": str(link),
                "KNOWTRACE_TEST_TARGET": str(target),
            },
            check=True,
            capture_output=True,
        )
    else:
        link.symlink_to(target, target_is_directory=True)


def test_file_tools_do_not_follow_links(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = tmp_path / "outside"
    target.mkdir()
    (target / "data.txt").write_text("external marker", encoding="utf-8")
    _link(root / "link", target)
    files = WorkspaceFiles(root)

    with pytest.raises(ValueError, match="符号链接"):
        files.read_file("link/data.txt", 1, 1)
    assert files.search_files("marker", ".", 10)["matches"] == []
    assert files.list_files(".", 10)["files"] == []


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


@pytest.fixture
def edit_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "core.autocrlf", "false")
    (root / "README.md").write_bytes("# 示例\r\n  端口 8000\r\n".encode("utf-8-sig"))
    (root / "notes.txt").write_text("keep my edit", encoding="utf-8")
    _git(root, "add", "README.md", "notes.txt")
    monkeypatch.setenv("KNOWTRACE_AGENT_STATE_DIR", str(tmp_path / "state"))
    return root


def _patch_provider(
    path: str, results: list[dict], *, old_text: str = "  端口 8000\n"
) -> Callable[[httpx.Request], httpx.Response]:
    def provider(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "apply_patch" in {tool["function"]["name"] for tool in payload["tools"]}
        messages = payload["messages"]
        if messages[-1]["role"] == "user":
            arguments = json.dumps(
                {"path": path, "old_text": old_text, "new_text": "  端口 9000\n"}
            )
            return _sse(({"tool_calls": [_tool("apply_patch", "patch", arguments)]}, "tool_calls"))
        assert messages[-1]["tool_call_id"] == "patch"
        results.append(json.loads(messages[-1]["content"]))
        return _sse(({"content": "检查结束。"}, "stop"))

    return provider


def test_cli_edit_and_offline_undo_in_git_repo(
    edit_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    readme = edit_repo / "README.md"
    before = readme.read_bytes()
    after = before.replace(b"8000", b"9000")
    unrelated = edit_repo / "notes.txt"
    unrelated.write_text("independent user edit", encoding="utf-8")
    results: list[dict] = []

    def answer(_: str) -> str:
        output = capsys.readouterr().out
        assert "--- a/README.md\n+++ b/README.md" in output
        assert "-  端口 8000" in output and "+  端口 9000" in output
        assert readme.read_bytes() == before
        return "y"

    _configure(monkeypatch, _patch_provider("README.md", results))
    monkeypatch.setattr("builtins.input", answer)
    assert main(["--edit", *_argv(edit_repo)]) == 0
    (result,) = results
    assert result["status"] == "applied"
    change_id = result["change_id"]
    assert re.fullmatch(r"[0-9a-f]{32}", change_id)
    assert f"回退 ID {change_id}" in capsys.readouterr().out
    assert readme.read_bytes() == after
    assert _git(edit_repo, "diff", "--name-only").splitlines() == [b"README.md", b"notes.txt"]

    def undo_answer(_: str) -> str:
        output = capsys.readouterr().out
        assert "-  端口 9000" in output and "+  端口 8000" in output
        assert readme.read_bytes() == after
        return "y"

    monkeypatch.setattr("builtins.input", undo_answer)
    monkeypatch.delenv("KNOWTRACE_ACCESS_TOKEN")
    monkeypatch.setattr(
        "app.features.agent.cli.CliSettings", lambda: pytest.fail("离线回退无需模型")
    )
    assert main(["--root", str(edit_repo), "--undo", change_id]) == 0
    assert readme.read_bytes() == before
    assert unrelated.read_text(encoding="utf-8") == "independent user edit"
    assert _git(edit_repo, "diff", "--name-only").splitlines() == [b"notes.txt"]
    assert set(_git(edit_repo, "status", "--short", "--untracked-files=all").splitlines()) == {
        b"AM notes.txt",
        b"A  README.md",
    }


@pytest.mark.parametrize("approve", [False, True])
def test_cli_rejects_denied_or_stale_preview(
    edit_repo: Path, monkeypatch: pytest.MonkeyPatch, approve: bool
) -> None:
    readme = edit_repo / "README.md"
    before = readme.read_bytes()
    manual = before.replace(b"8000", b"7777")
    results: list[dict] = []

    def answer(_: str) -> str:
        if approve:
            readme.write_bytes(manual)
            return "y"
        return ""

    _configure(monkeypatch, _patch_provider("README.md", results))
    monkeypatch.setattr("builtins.input", answer)
    assert main(["--edit", *_argv(edit_repo)]) == 0
    if approve:
        assert "文件在预览后已变化" in results[0]["error"]
        assert readme.read_bytes() == manual
    else:
        assert results[0]["status"] == "rejected"
        assert readme.read_bytes() == before
    assert not (edit_repo.parent / "state").exists()


@pytest.mark.parametrize("path", ["../outside/README.md", "link/README.md", ".git/config"])
def test_cli_blocks_edits_outside_git_worktree(
    edit_repo: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    outside = edit_repo.parent / "outside"
    outside.mkdir()
    target = outside / "README.md"
    before = (edit_repo / "README.md").read_bytes()
    target.write_bytes(before)
    if path.startswith("link/"):
        _link(edit_repo / "link", outside)
    results: list[dict] = []
    _configure(monkeypatch, _patch_provider(path, results))
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("越界补丁不应进入确认"))
    assert main(["--edit", *_argv(edit_repo)]) == 0
    assert "error" in results[0]
    assert target.read_bytes() == before
    assert _git(edit_repo, "diff") == b""
    assert not (edit_repo.parent / "state").exists()


def test_cli_rechecks_path_after_preview(edit_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = edit_repo / "docs"
    folder.mkdir()
    before = (edit_repo / "README.md").read_bytes()
    (folder / "README.md").write_bytes(before)
    outside = edit_repo.parent / "outside"
    outside.mkdir()
    target = outside / "README.md"
    target.write_bytes(before)
    results: list[dict] = []

    def answer(_: str) -> str:
        folder.rename(edit_repo / "moved")
        _link(folder, outside)
        return "y"

    _configure(monkeypatch, _patch_provider("docs/README.md", results))
    monkeypatch.setattr("builtins.input", answer)
    assert main(["--edit", *_argv(edit_repo)]) == 0
    assert "文件在预览后已变化" in results[0]["error"]
    assert target.read_bytes() == before
    assert (edit_repo / "moved" / "README.md").read_bytes() == before
    assert not (edit_repo.parent / "state").exists()


@pytest.mark.parametrize("change_during_confirmation", [False, True])
def test_undo_preserves_newer_file_changes(
    edit_repo: Path, monkeypatch: pytest.MonkeyPatch, change_during_confirmation: bool
) -> None:
    readme = edit_repo / "README.md"
    manual = readme.read_bytes().replace(b"8000", b"7777")
    results: list[dict] = []
    _configure(monkeypatch, _patch_provider("README.md", results))
    monkeypatch.setattr("builtins.input", lambda _: "y")
    assert main(["--edit", *_argv(edit_repo)]) == 0

    def answer(_: str) -> str:
        assert change_during_confirmation
        readme.write_bytes(manual)
        return "y"

    if not change_during_confirmation:
        readme.write_bytes(manual)
    monkeypatch.setattr("builtins.input", answer)
    assert main(["--root", str(edit_repo), "--undo", results[0]["change_id"]]) == 1
    assert readme.read_bytes() == manual

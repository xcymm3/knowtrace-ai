import json
import os
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


def test_file_tools_do_not_follow_links(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = tmp_path / "outside"
    target.mkdir()
    (target / "data.txt").write_text("external marker", encoding="utf-8")
    link = root / "link"
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
    files = WorkspaceFiles(root)

    with pytest.raises(ValueError, match="符号链接"):
        files.read_file("link/data.txt", 1, 1)
    assert files.search_files("marker", ".", 10)["matches"] == []
    assert files.list_files(".", 10)["files"] == []

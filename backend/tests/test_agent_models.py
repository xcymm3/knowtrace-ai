import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from uuid import uuid4

import pytest

from app.features.agent.cli import main


def _sse(protocol: str, text: str = "", calls: tuple = ()) -> bytes:
    if protocol != "messages":
        blocks = [
            {
                "delta": {"role": "assistant", "reasoning_content": "provider state"}
                if protocol == "deepseek"
                else {"role": "assistant"},
                "finish_reason": None,
            }
        ]
        for i, (name, arguments) in enumerate(calls):
            raw = json.dumps(arguments)
            blocks.extend(
                (
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": i,
                                    "id": f"call_{i}",
                                    "type": "function",
                                    "function": {"name": name, "arguments": raw[:4]},
                                }
                            ]
                        },
                        "finish_reason": None,
                    },
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": i,
                                    "function": {"arguments": raw[4:]},
                                }
                            ]
                        },
                        "finish_reason": None,
                    },
                )
            )
        if text:
            blocks.append({"delta": {"content": text}, "finish_reason": None})
        blocks.append({"delta": {}, "finish_reason": "tool_calls" if calls else "stop"})
        frames = "".join(f"data: {json.dumps({'choices': [block]})}\n\n" for block in blocks)
        return (frames + "data: [DONE]\n\n").encode()

    events = [
        {"type": "message_start"},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": "", "signature": ""},
        },
    ]
    events.extend(
        (
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "provider state"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "test-signature"},
            },
            {"type": "content_block_stop", "index": 0},
        )
    )
    for i, (name, arguments) in enumerate(calls, start=1):
        raw = json.dumps(arguments)
        events.append(
            {
                "type": "content_block_start",
                "index": i,
                "content_block": {
                    "type": "tool_use",
                    "id": f"call_{i - 1}",
                    "name": name,
                    "input": {},
                },
            }
        )
        for partial in (raw[:4], raw[4:]):
            events.append(
                {
                    "type": "content_block_delta",
                    "index": i,
                    "delta": {"type": "input_json_delta", "partial_json": partial},
                }
            )
        events.append({"type": "content_block_stop", "index": i})
    if text:
        events.extend(
            (
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "text_delta", "text": text},
                },
                {"type": "content_block_stop", "index": 1},
            )
        )
    events.extend(
        (
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use" if calls else "end_turn"},
            },
            {"type": "message_stop"},
        )
    )
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


@pytest.fixture
def gateway():
    errors = []

    class Gateway(BaseHTTPRequestHandler):
        handler = None

        def do_POST(self):
            try:
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                code, body = type(self).handler(self.path, self.headers, payload)
            except Exception as error:
                errors.append(error)
                code, body = 400, b""
            self.send_response(code)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    with ThreadingHTTPServer(("127.0.0.1", 0), Gateway) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            yield Gateway, f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join()
        assert not errors, errors


def _profile(tmp_path: Path, base: str) -> Path:
    config = tmp_path / "models.json"
    config.write_text(
        json.dumps(
            {
                "deepseek": {
                    "protocol": "openai-chat",
                    "base_url": base + "/deepseek/v1",
                    "model": "deepseek-test",
                    "api_key_env": "TEST_DEEPSEEK_KEY",
                },
                "second": {
                    "protocol": "openai-chat",
                    "base_url": base + "/second/v1",
                    "model": "second-test",
                    "api_key_env": "TEST_SECOND_KEY",
                    "token_field": "max_completion_tokens",
                },
                "messages": {
                    "protocol": "anthropic-messages",
                    "base_url": base + "/messages",
                    "model": "messages-test",
                    "api_key_env": "TEST_MESSAGES_KEY",
                },
                "text": {
                    "protocol": "openai-chat",
                    "base_url": base + "/text/v1",
                    "model": "text-test",
                },
            }
        ),
        encoding="utf-8-sig",
    )
    return config


def _results(protocol: str, messages: list) -> list[dict]:
    if protocol == "messages":
        if len(messages) <= 1:
            return []
        assert messages[-2]["content"][0] == {
            "type": "thinking",
            "thinking": "provider state",
            "signature": "test-signature",
        }
        assert messages[-1]["role"] == "user"
        native = messages[-1]["content"]
        assert all(block["type"] == "tool_result" for block in native)
        ids = [b["id"] for b in messages[-2]["content"] if b["type"] == "tool_use"]
        assert [b["tool_use_id"] for b in native] == ids
        return [json.loads(b["content"]) for b in native]
    if len(messages) <= 1 or messages[-1]["role"] != "tool":
        return []
    count = 0
    for item in reversed(messages):
        if item["role"] != "tool":
            break
        count += 1
    assistant = messages[-count - 1]
    if protocol == "deepseek":
        assert assistant["reasoning_content"] == "provider state"
    assert [m["tool_call_id"] for m in messages[-count:]] == [
        c["id"] for c in assistant["tool_calls"]
    ]
    return [json.loads(m["content"]) for m in messages[-count:]]


@pytest.mark.parametrize("protocol", ["deepseek", "second", "messages"])
def test_profiles_run_same_worktree_task(
    protocol: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    gateway,
) -> None:
    connection, base = gateway
    config = _profile(tmp_path, base)
    monkeypatch.setenv(f"TEST_{protocol.upper()}_KEY", f"key-{protocol}")
    monkeypatch.setenv("KNOWTRACE_ACCESS_TOKEN", "workspace-token")
    state = tmp_path / "state"
    monkeypatch.setenv("KNOWTRACE_AGENT_STATE_DIR", str(state))
    monkeypatch.setattr("builtins.input", lambda _: "y")
    root = tmp_path / "source"
    root.mkdir()
    sources = {
        "app.py": "def port():\n    return 8000\n",
        "config.json": '{"port": 8000}\n',
        "README.md": "Port: 8000\n",
        "verify.py": (
            "import json, pathlib, sys\nfrom app import port\n"
            "values = (port(), json.loads(pathlib.Path('config.json').read_text())['port'], "
            "int(pathlib.Path('README.md').read_text().split()[-1]))\n"
            "if values != (9000, 9000, 9000):\n    sys.exit(f'expected 9000, got {values}')\n"
            "print('all ports aligned')\n"
        ),
    }
    for name, text in sources.items():
        (root / name).write_text(text, encoding="utf-8")
    for args in (
        ["init", "--quiet"],
        ["add", "."],
        [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.test",
            "commit",
            "-m",
            "test: 创建模型验收仓库",
        ],
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    (root / "README.md").write_text("keep private edit\n", encoding="utf-8")
    commands = tmp_path / "commands.json"
    commands.write_text(json.dumps({"test": [sys.executable, "-B", "verify.py"]}), encoding="utf-8")

    turns = 0

    def reply(path, headers, payload):
        nonlocal turns
        native = protocol == "messages"
        assert path == f"/{protocol}/v1/" + ("messages" if native else "chat/completions")
        assert payload["model"] == f"{protocol}-test"
        if native:
            assert headers["x-api-key"] == "key-messages"
            assert headers["anthropic-version"] == "2023-06-01"
        else:
            assert headers["Authorization"] == f"Bearer key-{protocol}"
        cap = "max_completion_tokens" if protocol == "second" else "max_tokens"
        assert payload[cap] == 4096
        previous = _results(protocol, payload["messages"])
        tools = [t if native else t["function"] for t in payload.get("tools", [])]
        if not tools:
            return 200, _sse(protocol, "OK")
        if tools[0]["name"] == "knowtrace_probe":
            if previous:
                return 200, _sse(protocol, previous[0]["receipt"])
            return 200, _sse(protocol, calls=(("knowtrace_probe", {"value": "ping"}),))
        batch = next(tool for tool in tools if tool["name"] == "apply_patches")
        params = batch["input_schema" if native else "parameters"]
        assert params["properties"]["edits"]["items"]["required"] == [
            "path",
            "old_text",
            "new_text",
        ]
        turns += 1
        if turns == 1:
            calls = tuple(("read_file", {"path": file}) for file in ("app.py", "README.md"))
        elif turns == 2:
            assert "return 8000" in previous[0]["lines"][1]
            assert "Port: 8000" in previous[1]["lines"][0]
            calls = (("run_check", {"name": "test"}),)
        elif turns == 3:
            assert previous[0]["exit_code"] == 1
            assert "expected 9000, got (8000, 8000, 8000)" in previous[0]["output"]
            edits = [
                {"path": file, "old_text": "8000", "new_text": "9000"}
                for file in ("app.py", "config.json", "README.md")
            ]
            calls = (("apply_patches", {"edits": edits}),)
        elif turns == 4:
            assert previous[0]["status"] == "applied"
            calls = (("run_check", {"name": "test"}),)
        else:
            assert previous[0]["exit_code"] == 0 and "all ports aligned" in previous[0]["output"]
            return 200, _sse(protocol, "代码、配置与文档均通过端口检查。")
        return 200, _sse(protocol, calls=calls)

    connection.handler = reply
    selection = ["--model-config", str(config), "--profile", protocol]
    assert main([*selection, "--check-model"]) == 0
    assert json.loads(capsys.readouterr().out)["tool_round_trip"] is True
    assert (
        main(
            [
                *selection,
                "--worktree",
                "--root",
                str(root),
                "--workspace-id",
                str(uuid4()),
                "--commands",
                str(commands),
                "检查后统一项目的端口。",
            ]
        )
        == 0
    )
    assert turns == 5
    (result,) = (state / "worktrees").iterdir()
    for file in ("app.py", "config.json", "README.md"):
        assert "9000" in (result / file).read_text(encoding="utf-8")
    assert (root / "README.md").read_text(encoding="utf-8") == "keep private edit\n"
    output = capsys.readouterr().out
    assert "退出码 0" in output and "provider state" not in output


def test_text_only_endpoint_can_chat_without_workspace(
    tmp_path: Path, gateway, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, base = gateway
    config = _profile(tmp_path, base)

    def reply(path, headers, payload):
        assert path == "/text/v1/chat/completions"
        assert "Authorization" not in headers
        if "tools" in payload:
            return 400, b""
        return 200, _sse("second", "普通问答成功")

    connection.handler = reply
    args = ["--model-config", str(config), "--profile", "text"]
    assert main([*args, "--check-model"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["text_streaming"] is True and result["tool_round_trip"] is False
    assert main([*args, "--chat", "你好"]) == 0
    assert "普通问答成功" in capsys.readouterr().out
    monkeypatch.setenv("KNOWTRACE_ACCESS_TOKEN", "workspace-token")
    state = tmp_path / "state"
    monkeypatch.setenv("KNOWTRACE_AGENT_STATE_DIR", str(state))
    assert (
        main(
            [
                *args,
                "--worktree",
                "--root",
                str(tmp_path),
                "--workspace-id",
                str(uuid4()),
                "修改文件",
            ]
        )
        == 1
    )
    assert "未通过工具往返检测" in capsys.readouterr().err
    assert not state.exists()

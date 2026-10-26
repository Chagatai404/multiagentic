"""MCP server protocol and safety tests (in-process and over a real stdio subprocess)."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from eng.core.models import Task, TaskSpec
from eng.integrations.mcp import SUPPORTED_VERSIONS, McpServer
from eng.projects.config import load_config
from eng.storage.store import Store


def rpc(server: McpServer, method: str, params: Any = None, request_id: Any = 1) -> Any:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return server.handle(message)


def call(server: McpServer, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    reply = rpc(server, "tools/call", {"name": name, "arguments": arguments or {}})
    assert "result" in reply, reply
    return reply["result"]  # type: ignore[no-any-return]


@pytest.fixture
def server(repo: Path) -> McpServer:
    return McpServer(repo)


def make_task(repo: Path) -> Task:
    task = Task(
        project=repo,
        config=load_config(repo),
        spec=TaskSpec(description="Fix answer token=supersecret123", acceptance=["ok"]),
    )
    store = Store(repo)
    store.create(task)
    store.close()
    return task


def test_initialize_negotiates_version_and_declares_tools(server: McpServer) -> None:
    reply = rpc(server, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}})
    assert reply["result"]["protocolVersion"] == "2025-03-26"
    assert reply["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert reply["result"]["serverInfo"]["name"] == "eng"
    unknown = rpc(server, "initialize", {"protocolVersion": "1999-01-01"})
    assert unknown["result"]["protocolVersion"] == SUPPORTED_VERSIONS[0]
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert rpc(server, "ping")["result"] == {}


def test_tools_are_read_only_and_expose_no_approval_surface(repo: Path) -> None:
    tools = rpc(McpServer(repo), "tools/list")["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert names == {
        "eng_tasks",
        "eng_task_status",
        "eng_usage",
        "eng_plans",
        "eng_plan_status",
        "eng_triggers",
        "eng_refs",
    }
    assert all(tool["annotations"]["readOnlyHint"] for tool in tools)
    assert all(tool["inputSchema"]["additionalProperties"] is False for tool in tools)
    for forbidden in ("approve", "attest", "promote", "resume", "cancel", "integrate", "merge"):
        assert not any(forbidden in name for name in names)
    with_submit = rpc(McpServer(repo, allow_submit=True), "tools/list")["result"]["tools"]
    extra = [t for t in with_submit if t["name"] not in names]
    assert [t["name"] for t in extra] == ["eng_submit"]
    assert extra[0]["annotations"]["readOnlyHint"] is False
    assert not any(
        word in t["name"]
        for t in with_submit
        for word in ("approve", "attest", "promote", "resume")
    )


def test_task_tools_return_redacted_bounded_json(repo: Path, server: McpServer) -> None:
    task = make_task(repo)
    listing = json.loads(call(server, "eng_tasks")["content"][0]["text"])
    assert listing[0]["id"] == task.id and listing[0]["state"] == "CREATED"
    detail = call(server, "eng_task_status", {"task_id": task.id})
    assert detail["isError"] is False
    text = detail["content"][0]["text"]
    assert "supersecret123" not in text and "[REDACTED]" in text
    assert json.loads(text)["task"]["id"] == task.id
    assert "config" not in json.loads(text)["task"]
    usage = json.loads(call(server, "eng_usage", {"task_id": task.id})["content"][0]["text"])
    assert usage["invocations"] == 0 and usage["measured_account_spend"] is None
    assert call(server, "eng_plans")["isError"] is False
    assert call(server, "eng_triggers")["isError"] is False
    assert call(server, "eng_refs")["isError"] is False


def test_unknown_ids_are_tool_errors_and_bad_input_is_a_protocol_error(
    server: McpServer,
) -> None:
    missing = call(server, "eng_task_status", {"task_id": "nope"})
    assert missing["isError"] is True and "not found" in missing["content"][0]["text"]
    for arguments in (
        {"task_id": "../../etc/passwd"},
        {"task_id": "x" * 65},
        {"task_id": "ok", "extra": 1},
        {},
    ):
        reply = rpc(server, "tools/call", {"name": "eng_task_status", "arguments": arguments})
        assert reply["error"]["code"] == -32602
    assert rpc(server, "tools/call", {"name": "eng_approve"})["error"]["code"] == -32602
    # Value-range violations are tool execution errors the model can read and correct.
    for bad_limit in (0, 101, True, "5"):
        refused = call(server, "eng_tasks", {"limit": bad_limit})
        assert refused["isError"] is True and "limit" in refused["content"][0]["text"]
    assert rpc(server, "tools/call", {"arguments": {}})["error"]["code"] == -32602


def test_protocol_errors(server: McpServer) -> None:
    assert rpc(server, "nope/method")["error"]["code"] == -32601
    assert server.handle({"method": "ping"})["error"]["code"] == -32600  # type: ignore[index]
    assert server.handle("string")["error"]["code"] == -32600  # type: ignore[index]
    assert server.handle([])["error"]["code"] == -32600  # type: ignore[index]
    batch = server.handle(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        ]
    )
    assert [reply["id"] for reply in batch] == [1, 2]  # type: ignore[union-attr]
    # An unknown notification is never answered.
    assert server.handle({"jsonrpc": "2.0", "method": "mystery"}) is None


def test_submit_routes_one_idempotent_task_and_refuses_when_nested(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = McpServer(repo, allow_submit=True)
    monkeypatch.setenv("ENG_ACTIVE", "1")
    nested = call(server, "eng_submit", {"description": "fix it", "request_id": "r1"})
    assert nested["isError"] is True and "Nested" in nested["content"][0]["text"]
    monkeypatch.delenv("ENG_ACTIVE")
    # The default provider would be a real model; route with a fake provider via config.
    config = repo / ".engineering" / "project.yaml"
    config.write_text(config.read_text().replace("provider: codex", "provider: fake"))
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c"],
        check=True,
        capture_output=True,
    )
    first = call(server, "eng_submit", {"description": "fix the answer", "request_id": "r2"})
    decision = json.loads(first["content"][0]["text"])
    assert first["isError"] is False and decision["action"] == "route" and decision["task_id"]
    again = json.loads(
        call(server, "eng_submit", {"description": "fix the answer", "request_id": "r2"})[
            "content"
        ][0]["text"]
    )
    assert again["action"] == "duplicate" and again["task_id"] == decision["task_id"]
    deadline = time.monotonic() + 120
    store = Store(repo)
    while store.load(decision["task_id"]).state.value in {
        "CREATED",
        "CLASSIFYING",
        "PREPARING_CONTEXT",
        "IMPLEMENTING",
        "VERIFYING",
    }:
        assert time.monotonic() < deadline
        time.sleep(0.5)
    store.close()


def test_stdio_subprocess_end_to_end(repo: Path) -> None:
    task = make_task(repo)
    environment = {k: v for k, v in os.environ.items() if k != "ENG_ACTIVE"}
    process = subprocess.Popen(
        [sys.executable, "-m", "eng", "mcp", "serve", "-p", str(repo)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    assert process.stdin and process.stdout
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "eng_tasks", "arguments": {}},
        },
    ]
    process.stdin.write("not json\n")
    for message in messages:
        process.stdin.write(json.dumps(message) + "\n")
    process.stdin.close()
    replies = [json.loads(line) for line in process.stdout]
    process.wait(timeout=30)
    assert process.returncode == 0
    assert replies[0]["error"]["code"] == -32700  # parse error reported, loop continues
    by_id = {reply["id"]: reply for reply in replies[1:]}
    assert set(by_id) == {1, 2, 3}  # the notification produced no output line
    assert by_id[1]["result"]["protocolVersion"] == "2025-06-18"
    assert len(by_id[2]["result"]["tools"]) == 7
    assert task.id in by_id[3]["result"]["content"][0]["text"]

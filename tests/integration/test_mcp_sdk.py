"""Interoperability with the official MCP Python SDK client.

Skipped unless the `mcp` package is installed (it is not a dependency of eng; CI installs
it in a dedicated job). Attribute access tolerates the SDK's camelCase and snake_case eras.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


def attr(obj: Any, *names: str) -> Any:
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    raise AttributeError(names)


async def exercise(project: Path) -> dict[str, Any]:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "eng", "mcp", "serve", "-p", str(project)]
    )
    out: dict[str, Any] = {}
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            out["server"] = attr(init, "server_info", "serverInfo").name
            tools = await session.list_tools()
            out["tools"] = {t.name: t for t in tools.tools}
            listed = await session.call_tool("eng_tasks", {"limit": 3})
            out["listed_error"] = attr(listed, "is_error", "isError")
            missing = await session.call_tool("eng_task_status", {"task_id": "missing"})
            out["missing_error"] = attr(missing, "is_error", "isError")
            out["missing_text"] = missing.content[0].text
            await session.send_ping()
    return out


def test_official_client_lists_calls_and_pings(repo: Path) -> None:
    out = asyncio.run(exercise(repo))
    assert out["server"] == "eng"
    assert len(out["tools"]) == 7
    for tool in out["tools"].values():
        annotations = tool.annotations
        assert attr(annotations, "read_only_hint", "readOnlyHint") is True
    assert out["listed_error"] is False
    assert out["missing_error"] is True and "not found" in out["missing_text"]

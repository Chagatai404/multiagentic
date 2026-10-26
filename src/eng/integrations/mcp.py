"""Optional MCP server (stdio, newline-delimited JSON-RPC 2.0) exposing eng state.

No extra dependency. The server is bound to one project at start; tools take ids, never
paths. Every tool is read-only except ``eng_submit``, which exists only with
``--allow-submit`` and routes a task through the normal trigger path (clean checkout,
claim/dedup, detached runner). There is deliberately no tool that approves, resumes,
cancels, integrates or promotes: those stay explicit human CLI actions, so a model that
can call this server can never grant itself approval.
"""

import io
import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

from eng import __version__

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_TEXT = 60_000
MAX_EVENTS = 20

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL = (
    -32700,
    -32600,
    -32601,
    -32602,
    -32603,
)

ID = {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[a-zA-Z0-9_-]+$"}
LIMIT = {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


class ToolError(Exception):
    """A failure the model should see as a tool result (isError), not a protocol error."""


class McpServer:
    def __init__(self, root: Path, *, allow_submit: bool = False) -> None:
        self.root = root
        self.allow_submit = allow_submit
        self.initialized = False
        self.tools: dict[str, tuple[str, dict[str, Any], Callable[[dict[str, Any]], Any], bool]] = {
            "eng_tasks": (
                "List this project's tasks (id, state, message), newest first.",
                _schema({"limit": LIMIT}),
                self._tasks,
                True,
            ),
            "eng_task_status": (
                "Show one task: state, checkpoint, verification results and recent events.",
                _schema({"task_id": ID}, ["task_id"]),
                self._task_status,
                True,
            ),
            "eng_usage": (
                "Report reported token/cost coverage for a task across all executions.",
                _schema({"task_id": ID}, ["task_id"]),
                self._usage,
                True,
            ),
            "eng_plans": (
                "List this project's parallel plans.",
                _schema({"limit": LIMIT}),
                self._plans,
                True,
            ),
            "eng_plan_status": (
                "Show one plan: node statuses, integration head, verification, recent events.",
                _schema({"plan_id": ID}, ["plan_id"]),
                self._plan_status,
                True,
            ),
            "eng_triggers": (
                "List recent trigger records (digests and status, never raw prompts).",
                _schema({"limit": LIMIT}),
                self._triggers,
                True,
            ),
            "eng_refs": (
                "List recent commit verifications from Git hooks and `eng verify-ref`.",
                _schema({"limit": LIMIT}),
                self._refs,
                True,
            ),
        }
        if allow_submit:
            self.tools["eng_submit"] = (
                "Start ONE engineering task in a detached runner (may call a billable model "
                "provider). Requires a clean checkout. Approvals, resumes and merges remain "
                "human CLI actions. request_id makes retries idempotent.",
                _schema(
                    {
                        "description": {"type": "string", "minLength": 1, "maxLength": 20000},
                        "request_id": ID,
                    },
                    ["description", "request_id"],
                ),
                self._submit,
                False,
            )

    # -- tools -------------------------------------------------------------------------

    def _store(self) -> Any:
        from eng.storage.store import Store

        return Store(self.root)

    @staticmethod
    def _limit(arguments: dict[str, Any]) -> int:
        value = arguments.get("limit", 20)
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 100:
            raise ValueError("limit must be an integer from 1 to 100")
        return value

    def _tasks(self, arguments: dict[str, Any]) -> Any:
        limit = self._limit(arguments)
        store = self._store()
        try:
            return [
                {"id": t.id, "state": t.state.value, "message": t.message}
                for t in store.list_tasks()[:limit]
            ]
        finally:
            store.close()

    def _task_status(self, arguments: dict[str, Any]) -> Any:
        store = self._store()
        try:
            task = store.load(arguments["task_id"])
            return {
                "task": task.model_dump(mode="json", exclude={"config"}),
                "events": store.events(task.id)[-MAX_EVENTS:],
            }
        finally:
            store.close()

    def _usage(self, arguments: dict[str, Any]) -> Any:
        from eng.core.accounting import usage_report

        store = self._store()
        try:
            task = store.load(arguments["task_id"])
            report = usage_report(store.invocations(task.id), task.config.pricing)
            return report.model_dump(mode="json")
        finally:
            store.close()

    def _plans(self, arguments: dict[str, Any]) -> Any:
        limit = self._limit(arguments)
        store = self._store()
        try:
            return [
                {"id": p.id, "name": p.spec.name, "status": p.status.value, "message": p.message}
                for p in store.list_plans()[:limit]
            ]
        finally:
            store.close()

    def _plan_status(self, arguments: dict[str, Any]) -> Any:
        store = self._store()
        try:
            plan = store.load_plan(arguments["plan_id"])
            return {
                "plan": plan.model_dump(mode="json", exclude={"spec"}),
                "events": store.plan_events(plan.id)[-MAX_EVENTS:],
            }
        finally:
            store.close()

    def _triggers(self, arguments: dict[str, Any]) -> Any:
        store = self._store()
        try:
            return [r.model_dump(mode="json") for r in store.triggers(self._limit(arguments))]
        finally:
            store.close()

    def _refs(self, arguments: dict[str, Any]) -> Any:
        store = self._store()
        try:
            return [
                {
                    "id": c.id,
                    "commit": c.commit,
                    "origin": c.origin,
                    "status": c.status,
                    "message": c.message,
                }
                for c in store.ref_checks(self._limit(arguments))
            ]
        finally:
            store.close()

    def _submit(self, arguments: dict[str, Any]) -> Any:
        from eng.core.models import now
        from eng.core.triggers import TriggerEnvelope, TriggerMode, TriggerOrigin
        from eng.integrations.hook import submit

        if os.environ.get("ENG_ACTIVE"):
            raise ToolError("Nested eng execution is disabled")
        envelope = TriggerEnvelope(
            origin=TriggerOrigin.CLI,
            session_id="mcp",
            turn_id=arguments["request_id"],
            cwd=str(self.root),
            prompt="eng: " + arguments["description"],
            received_at=now(),
        )
        decision, _ = submit(envelope, TriggerMode.MANUAL, project=self.root)
        return decision.model_dump(mode="json")

    # -- protocol ----------------------------------------------------------------------

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def _call(self, params: Any) -> dict[str, Any]:
        from eng.execution.process import redact, redact_data

        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            raise ValueError("tools/call needs a tool name")
        name = params["name"]
        if name not in self.tools:
            raise ValueError(f"Unknown tool: {name}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        _, schema, handler, _ = self.tools[name]
        unknown = set(arguments) - set(schema["properties"])
        missing = [key for key in schema["required"] if key not in arguments]
        if unknown or missing:
            raise ValueError(f"Invalid arguments (unknown: {sorted(unknown)}, missing: {missing})")
        for key, spec in schema["properties"].items():
            value = arguments.get(key)
            if spec.get("type") == "string" and key in arguments:
                pattern = spec.get("pattern")
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{key} must be a non-empty string")
                if pattern and not re.fullmatch(pattern, value):
                    raise ValueError(f"{key} has an invalid format")
                if len(value) > spec.get("maxLength", MAX_TEXT):
                    raise ValueError(f"{key} is too long")
        try:
            result = handler(arguments)
            text = json.dumps(redact_data(result), indent=2, default=str)
            is_error = False
        except (ToolError, OSError) as error:
            text, is_error = redact(f"Error: {error}"), True
        except ValueError as error:  # unknown ids, refused preconditions: visible to the model
            text, is_error = redact(f"Error: {error}"), True
        return {
            "content": [{"type": "text", "text": text[:MAX_TEXT]}],
            "isError": is_error,
        }

    def handle(self, message: Any) -> dict[str, Any] | list[dict[str, Any]] | None:
        if isinstance(message, list):
            if not message:
                return self._error(None, INVALID_REQUEST, "Empty batch")
            replies = [reply for item in message if (reply := self._single(item)) is not None]
            return replies or None
        return self._single(message)

    def _single(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return self._error(None, INVALID_REQUEST, "Not a JSON-RPC 2.0 message")
        method = message.get("method")
        request_id = message.get("id")
        is_notification = "id" not in message
        if not isinstance(method, str):
            if "result" in message or "error" in message:
                return None  # a client response to a server request: we send none
            return self._error(request_id, INVALID_REQUEST, "Missing method")
        params = message.get("params")
        try:
            if method == "initialize":
                version = params.get("protocolVersion") if isinstance(params, dict) else None
                chosen = version if version in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
                self.initialized = True
                result: dict[str, Any] = {
                    "protocolVersion": chosen,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "eng", "version": __version__},
                    "instructions": (
                        "Read-only visibility into eng tasks, plans, triggers and commit "
                        "verifications"
                        + ("; eng_submit can start one task." if self.allow_submit else ".")
                        + " Approvals and merges are human CLI actions."
                    ),
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": name,
                            "description": description,
                            "inputSchema": schema,
                            "annotations": {
                                "readOnlyHint": read_only,
                                "destructiveHint": False,
                                "openWorldHint": False,
                            },
                        }
                        for name, (description, schema, _, read_only) in self.tools.items()
                    ]
                }
            elif method == "tools/call":
                result = self._call(params)
            elif method.startswith("notifications/"):
                return None
            else:
                if is_notification:
                    return None
                return self._error(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")
        except ValueError as error:
            if is_notification:
                return None
            return self._error(request_id, INVALID_PARAMS, str(error))
        except Exception as error:  # noqa: BLE001 - never crash the stdio loop
            if is_notification:
                return None
            return self._error(request_id, INTERNAL, type(error).__name__)
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve(server: McpServer, stdin: IO[str], stdout: IO[str]) -> None:
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply: Any = server._error(None, PARSE_ERROR, "Parse error")
        else:
            reply = server.handle(message)
        if reply is not None:
            stdout.write(json.dumps(reply, separators=(",", ":")) + "\n")
            stdout.flush()


def serve_stdio(server: McpServer) -> None:
    """Serve over the process's stdio as UTF-8 with LF-delimited messages."""
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace", newline="\n")
    stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n", write_through=True)
    serve(server, stdin, stdout)


def main(arguments: list[str] | None = None) -> int:
    from eng.execution.workspace import repository_root

    args = sys.argv[1:] if arguments is None else arguments
    project = Path(".")
    if "--project" in args and args.index("--project") + 1 < len(args):
        project = Path(args[args.index("--project") + 1])
    server = McpServer(repository_root(project), allow_submit="--allow-submit" in args)
    serve_stdio(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

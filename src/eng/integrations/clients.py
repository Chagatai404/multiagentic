"""Client hook adapters: parse hook stdin, render hook stdout and build hook commands (M4)."""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from eng.core.triggers import (
    TriggerAction,
    TriggerDecision,
    TriggerEnvelope,
    TriggerMode,
    TriggerOrigin,
)

HOOK_MODULE = "eng.integrations.hook"
REASON_LIMIT = 1000
HOOK_CLIENTS = (TriggerOrigin.CLAUDE_CODE, TriggerOrigin.CODEX)
_PROVIDER = re.compile(r"[a-z][a-z0-9-]{0,39}")


def client_origin(client: str) -> TriggerOrigin:
    if client not in {origin.value for origin in HOOK_CLIENTS}:
        raise ValueError(f"unsupported hook client: {client}")
    return TriggerOrigin(client)


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) and value else None


def parse_hook_input(origin: TriggerOrigin, raw: str, *, received_at: str) -> TriggerEnvelope:
    if not raw.strip():
        raise ValueError("hook input is empty")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"hook input is not JSON: {error.msg}") from error
    if not isinstance(data, dict):
        raise ValueError("hook input must be a JSON object")
    prompt = data.get("prompt")
    if not isinstance(prompt, str):
        raise ValueError("hook input prompt must be a string")
    cwd = _optional_str(data, "cwd")
    if cwd is None:
        raise ValueError("hook input cwd must be a non-empty string")
    return TriggerEnvelope(
        origin=origin,
        event=_optional_str(data, "hook_event_name") or "UserPromptSubmit",
        session_id=_optional_str(data, "session_id"),
        # Claude Code sends prompt_id, Codex sends turn_id; both are the idempotency identity.
        turn_id=_optional_str(data, "prompt_id") or _optional_str(data, "turn_id"),
        cwd=cwd,
        prompt=prompt,
        received_at=received_at,
    )


def render_decision(
    origin: TriggerOrigin, decision: TriggerDecision, *, project: Path
) -> tuple[int, str]:
    if decision.action not in (TriggerAction.ROUTE, TriggerAction.DUPLICATE):
        return 0, ""
    if not decision.task_id:
        return 0, ""
    status = subprocess.list2cmdline(["eng", "status", decision.task_id, "-p", str(project)])
    if decision.action is TriggerAction.DUPLICATE:
        lead = f"eng already has task {decision.task_id} for this request."
    else:
        lead = f"eng started task {decision.task_id} for this request."
    reason = f"{lead} The prompt was not sent to the assistant. Check progress with: {status}"
    if len(reason) > REASON_LIMIT:
        reason = reason[: REASON_LIMIT - 3] + "..."
    return 0, json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False)


def render_error(origin: TriggerOrigin, message: str) -> tuple[int, str]:
    text = f"eng {origin.value} hook failed open: {message}"
    return 0, json.dumps({"systemMessage": text[:REASON_LIMIT]}, ensure_ascii=False)


def hook_command(
    client: str, *, mode: str, provider: str, project: Path | None = None
) -> list[str]:
    origin = client_origin(client)
    if not _PROVIDER.fullmatch(provider):
        raise ValueError(f"invalid provider name: {provider!r}")
    argv = [
        sys.executable,
        "-m",
        HOOK_MODULE,
        origin.value,
        "--mode",
        TriggerMode(mode).value,
        "--provider",
        provider,
    ]
    if project is not None:
        # Binds the hook to the project it was installed in; other repositories bypass.
        argv += ["--project", str(project.resolve())]
    return argv

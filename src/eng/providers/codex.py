import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from eng.core.models import Capabilities, ProviderRequest, ProviderResult, ProviderStatus, Usage
from eng.execution.process import redact, run_process


def codex_command() -> list[str]:
    """Resolve npm's JS entry point on Windows instead of executing a .cmd via a shell."""
    executable = shutil.which("codex")
    if executable is None:
        raise ValueError("Codex CLI not found; install it and run codex login")
    if Path(executable).suffix.lower() in {".cmd", ".ps1", ".bat"}:
        entry = Path(executable).parent / "node_modules/@openai/codex/bin/codex.js"
        node = shutil.which("node")
        if not entry.is_file() or node is None:
            raise ValueError(
                "Cannot resolve Codex npm entry point; install a native CLI or Node.js"
            )
        return [node, str(entry)]
    return [executable]


def parse_events(stdout: str) -> ProviderResult:
    summary = ""
    session_id = None
    usage = Usage()
    completed = False
    try:
        for line in stdout.splitlines():
            if not line.strip():
                continue
            event: Any = json.loads(line)
            if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                raise ValueError("Event must be an object with a type")
            if event["type"] in {"turn.failed", "error"}:
                return ProviderResult(
                    status="error",
                    error_kind="provider_error",
                    summary=redact(str(event.get("error", event.get("message", "")))),
                )
            if event["type"] == "thread.started":
                session_id = event.get("thread_id")
                if not isinstance(session_id, str):
                    raise ValueError("thread_id must be a string")
            if event["type"] == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message":
                    summary = item.get("text", "")
                    if not isinstance(summary, str):
                        raise ValueError("agent_message text must be a string")
            if event["type"] == "turn.completed":
                completed = True
                raw = event.get("usage")
                if raw is not None and not isinstance(raw, dict):
                    raise ValueError("usage must be an object when reported")
                if isinstance(raw, dict):
                    usage = Usage(
                        input_tokens=raw.get("input_tokens"),
                        output_tokens=raw.get("output_tokens"),
                        cached_input_tokens=raw.get("cached_input_tokens"),
                        reasoning_tokens=raw.get("reasoning_output_tokens"),
                        source="provider",
                    )
    except (ValueError, TypeError, AttributeError) as error:
        return ProviderResult(status="error", error_kind="malformed_output", summary=str(error))
    if not completed:
        return ProviderResult(
            status="error",
            error_kind="incomplete_output",
            summary="No turn.completed event received",
        )
    return ProviderResult(
        status="success", summary=redact(summary), usage=usage, session_id=session_id
    )


class CodexProvider:
    name = "codex"
    capabilities = Capabilities(
        kind="coding_cli",
        file_editing=True,
        tool_execution=True,
        streaming=False,
        token_reporting=True,
        working_directory_isolation=True,
        permission_controls=True,
    )

    async def execute(
        self,
        request: ProviderRequest,
        artifact_dir: Path,
        cancelled: Callable[[], bool],
    ) -> ProviderResult:
        try:
            command = codex_command()
        except ValueError as error:
            return ProviderResult(status="error", error_kind="unavailable", summary=str(error))
        command += [
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--color",
            "never",
            "--sandbox",
            "workspace-write",
            "-c",
            'approval_policy="never"',
            "-c",
            "sandbox_workspace_write.network_access=false",
            "--cd",
            str(request.workspace),
        ]
        if request.model:
            command += ["--model", request.model]
        command += ["-"]
        result = await run_process(
            command,
            request.workspace,
            request.timeout_seconds,
            stdin=request.prompt,
            cancelled=cancelled,
            provider=True,
        )
        artifact_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - small local evidence writes
        (artifact_dir / "provider.jsonl").write_text(redact(result.stdout), encoding="utf-8")
        (artifact_dir / "provider.stderr.log").write_text(redact(result.stderr), encoding="utf-8")
        if result.reason:
            status: ProviderStatus = "error"
            if result.reason == "cancelled":
                status = "cancelled"
            elif result.reason == "timeout":
                status = "timeout"
            return ProviderResult(
                status=status,
                error_kind=result.reason,
                summary=redact(result.stderr[-4000:]),
                duration_seconds=result.duration_seconds,
            )
        if result.exit_code != 0:
            stderr = result.stderr.lower()
            kind = (
                "authentication"
                if any(s in stderr for s in ("unauthorized", "login", "401"))
                else "exit_code"
            )
            return ProviderResult(
                status="error",
                error_kind=kind,
                summary=redact(result.stderr[-4000:]),
                duration_seconds=result.duration_seconds,
            )
        parsed = parse_events(result.stdout)
        parsed.duration_seconds = result.duration_seconds
        return parsed

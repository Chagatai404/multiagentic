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


# Each JSONL record is bounded independently; large streams keep late usage.
MAX_RECORD_CHARS = 8_000_000
MAX_SUMMARY_CHARS = 64_000


class EventParser:
    def __init__(self) -> None:
        self.pending = ""
        self.dropping = False
        self.summary = ""
        self.session_id: str | None = None
        self.usage = Usage()
        self.completed = False
        self.error_kind: str | None = None
        self.error_summary = ""

    def feed(self, text: str) -> None:
        # splitlines creates only chunk-sized temporaries; pending has a fixed cap.
        pieces = text.split("\n")
        for index, piece in enumerate(pieces):
            if not self.dropping:
                if len(self.pending) + len(piece) > MAX_RECORD_CHARS:
                    self.pending = ""
                    self.dropping = True
                    self.error_kind = "oversized_output"
                    self.error_summary = "Codex JSONL record exceeds 8000000 characters"
                else:
                    self.pending += piece
            if index < len(pieces) - 1:
                if not self.dropping:
                    self.record(self.pending)
                self.pending = ""
                self.dropping = False

    def record(self, line: str) -> None:
        if not line.strip():
            return
        try:
            event: Any = json.loads(line)
            if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                raise ValueError("Event must be an object with a type")
            if event["type"] in {"turn.failed", "error"}:
                self.error_kind = self.error_kind or "provider_error"
                self.error_summary = redact(str(event.get("error", event.get("message", ""))))[
                    :MAX_SUMMARY_CHARS
                ]
            if event["type"] == "thread.started":
                session = event.get("thread_id")
                if not isinstance(session, str):
                    raise ValueError("thread_id must be a string")
                self.session_id = session[:MAX_SUMMARY_CHARS]
            if event["type"] == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message":
                    summary = item.get("text", "")
                    if not isinstance(summary, str):
                        raise ValueError("agent_message text must be a string")
                    self.summary = redact(summary)[:MAX_SUMMARY_CHARS]
            if event["type"] == "turn.completed":
                self.completed = True
                raw = event.get("usage")
                if raw is not None and not isinstance(raw, dict):
                    raise ValueError("usage must be an object when reported")
                if isinstance(raw, dict):
                    self.usage = Usage(
                        input_tokens=raw.get("input_tokens"),
                        output_tokens=raw.get("output_tokens"),
                        cached_input_tokens=raw.get("cached_input_tokens"),
                        reasoning_tokens=raw.get("reasoning_output_tokens"),
                        source="provider",
                    )
        except (ValueError, TypeError, AttributeError) as error:
            self.error_kind = self.error_kind or "malformed_output"
            self.error_summary = redact(str(error))[:MAX_SUMMARY_CHARS]

    def finish(self) -> ProviderResult:
        if self.pending and not self.dropping:
            self.record(self.pending)
        self.pending = ""
        kind = self.error_kind or (None if self.completed else "incomplete_output")
        return ProviderResult(
            status="error" if kind else "success",
            error_kind=kind,
            summary=self.error_summary or (
                "No turn.completed event received" if kind == "incomplete_output" else self.summary
            ),
            usage=self.usage,
            session_id=self.session_id,
        )


def parse_events(stdout: str) -> ProviderResult:
    parser = EventParser()
    parser.feed(stdout)
    return parser.finish()


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
        parser = EventParser()
        result = await run_process(
            command,
            request.workspace,
            request.timeout_seconds,
            stdin=request.prompt,
            cancelled=cancelled,
            provider=True,
            stdout_path=artifact_dir / "provider.jsonl",
            stderr_path=artifact_dir / "provider.stderr.log",
            stdout_json=True,
            stdout_observer=parser.feed,
        )
        # Legacy/mocked transports return only strings and do not call observers.
        if result.capture_metadata is None:
            artifact_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
            (artifact_dir / "provider.jsonl").write_text(redact(result.stdout), encoding="utf-8")
            (artifact_dir / "provider.stderr.log").write_text(
                redact(result.stderr), encoding="utf-8"
            )
            parser.feed(result.stdout)
        parsed = parser.finish()
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
                usage=parsed.usage,
                session_id=parsed.session_id,
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
                usage=parsed.usage,
                session_id=parsed.session_id,
            )
        parsed.duration_seconds = result.duration_seconds
        return parsed

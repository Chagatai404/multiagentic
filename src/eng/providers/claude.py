"""Claude Code print/JSON transport; command execution remains outside its tool set."""

import json
import math
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from eng.core.models import Capabilities, ProviderRequest, ProviderResult, ProviderStatus, Usage
from eng.execution.process import redact, redact_data, run_process


def claude_command() -> list[str]:
    """Resolve known npm native/legacy entries without executing a shell shim."""
    executable = shutil.which("claude")
    if executable is None:
        raise ValueError("Claude CLI not found; install it and run claude auth login")
    if Path(executable).suffix.lower() in {".cmd", ".ps1", ".bat"}:
        package = Path(executable).parent / "node_modules/@anthropic-ai/claude-code"
        native = package / "bin/claude.exe"
        if native.is_file():
            return [str(native)]
        legacy = package / "cli.js"
        node = shutil.which("node")
        if legacy.is_file() and node is not None:
            return [node, str(legacy)]
        raise ValueError("Cannot resolve Claude npm entry point; install a native CLI or Node.js")
    return [executable]


def _counter(raw: dict[str, Any], name: str) -> int | None:
    value = raw.get(name)
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError(f"{name} must be a nonnegative integer when reported")
    return value


def parse_result(stdout: str, exit_code: int | None = 0) -> ProviderResult:
    """Validate a single CLI result, retaining reported usage on valid failures."""
    try:
        event = json.loads(stdout)
        if not isinstance(event, dict) or event.get("type") != "result":
            raise ValueError("Expected a single result object")
        subtype = event.get("subtype")
        if not isinstance(subtype, str) or not subtype:
            raise ValueError("result subtype must be a nonempty string")
        if type(event.get("is_error")) is not bool:
            raise ValueError("result is_error must be a boolean")
        api_status = event.get("api_error_status")
        if api_status is not None and (type(api_status) is not int or not 100 <= api_status <= 599):
            raise ValueError("api_error_status must be an HTTP status integer when reported")
        summary = event.get("result", "")
        if summary is None:
            summary = ""
        if not isinstance(summary, str):
            raise ValueError("result text must be a string")
        session = event.get("session_id")
        if session is not None and not isinstance(session, str):
            raise ValueError("session_id must be a string when reported")
        errors = event.get("errors", [])
        if errors is None:
            errors = []
        if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
            raise ValueError("errors must be a list of strings")
        denials = event.get("permission_denials", [])
        if denials is None:
            denials = []
        if not isinstance(denials, list) or any(not isinstance(item, dict) for item in denials):
            raise ValueError("permission_denials must be a list of objects")
        raw = event.get("usage")
        if raw is not None and not isinstance(raw, dict):
            raise ValueError("usage must be an object when reported")
        cost = event.get("total_cost_usd")
        if cost is not None and (
            type(cost) not in {int, float} or not math.isfinite(cost) or cost < 0
        ):
            raise ValueError("total_cost_usd must be a finite nonnegative number when reported")
        usage = Usage(
            input_tokens=_counter(raw or {}, "input_tokens"),
            output_tokens=_counter(raw or {}, "output_tokens"),
            cached_input_tokens=_counter(raw or {}, "cache_read_input_tokens"),
            cache_creation_input_tokens=_counter(raw or {}, "cache_creation_input_tokens"),
            cost_usd=cost,
            cost_source="client_estimate" if cost is not None else "unknown",
        )
        if any(
            value is not None
            for value in (
                usage.input_tokens,
                usage.output_tokens,
                usage.cached_input_tokens,
                usage.cache_creation_input_tokens,
                usage.cost_usd,
            )
        ):
            usage.source = "provider"
    except (ValueError, TypeError, OverflowError) as error:
        return ProviderResult(status="error", error_kind="malformed_output", summary=str(error))
    summary = redact("\n".join(filter(None, [summary, *errors])))
    kind = None
    if denials:
        kind = "permission_denied"
    elif api_status in {401, 403}:
        kind = "authentication"
    elif event["is_error"] or subtype != "success" or errors or api_status is not None:
        kind = (
            "authentication"
            if any(word in summary.lower() for word in ("unauthorized", "login", "401"))
            else "provider_error"
        )
    elif exit_code != 0:
        kind = "exit_code"
    return ProviderResult(
        status="error" if kind else "success",
        error_kind=kind,
        summary=summary,
        usage=usage,
        session_id=session,
    )


class ClaudeProvider:
    name = "claude"
    capabilities = Capabilities(
        kind="coding_cli",
        file_editing=True,
        token_reporting=True,
        working_directory_isolation=True,
        permission_controls=True,
        # CLI total_cost_usd is a client estimate, not measured account spend.
        cost_reporting=False,
    )

    async def execute(
        self,
        request: ProviderRequest,
        artifact_dir: Path,
        cancelled: Callable[[], bool],
    ) -> ProviderResult:
        try:
            command = claude_command()
        except ValueError as error:
            return ProviderResult(status="error", error_kind="unavailable", summary=str(error))
        command += [
            "--safe-mode",
            "--restricted",
            "--print",
            "--output-format",
            "json",
            "--no-session-persistence",
            "--permission-mode",
            "acceptEdits",
            "--permission-prompts",
            "none",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--setting-sources",
            "",
            "--tools",
            "Read,Edit,Write,Glob,Grep",
            "--disable-slash-commands",
            "--no-chrome",
        ]
        if request.model:
            command += ["--model", request.model]
        result = await run_process(
            command,
            request.workspace,
            request.timeout_seconds,
            stdin=request.prompt,
            cancelled=cancelled,
            provider="claude",
        )
        artifact_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
        try:
            evidence = json.dumps(redact_data(json.loads(result.stdout)), ensure_ascii=False)
        except ValueError:
            evidence = redact(result.stdout)
        (artifact_dir / "provider.json").write_text(evidence, encoding="utf-8")
        (artifact_dir / "provider.stderr.log").write_text(redact(result.stderr), encoding="utf-8")
        parsed = parse_result(result.stdout, result.exit_code)
        if result.reason:
            status: ProviderStatus = "error"
            if result.reason == "cancelled":
                status = "cancelled"
            elif result.reason == "timeout":
                status = "timeout"
            parsed.status = status
            parsed.error_kind = result.reason
            parsed.summary = redact(result.stderr[-4000:])
        elif result.exit_code != 0 and not result.stdout.strip():
            parsed.error_kind = (
                "authentication"
                if any(word in result.stderr.lower() for word in ("unauthorized", "login", "401"))
                else "exit_code"
            )
            parsed.summary = redact(result.stderr[-4000:])
        parsed.duration_seconds = result.duration_seconds
        return parsed

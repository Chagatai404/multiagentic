import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from eng.core.models import ProviderRequest, Usage
from eng.execution.process import ProcessResult, clean_environment
from eng.providers.base import Provider
from eng.providers.claude import ClaudeProvider, claude_command, parse_result


def result_event(**overrides: Any) -> dict[str, Any]:
    return {"type": "result", "subtype": "success", "is_error": False, **overrides}


def test_usage_and_client_estimate_semantics() -> None:
    result = parse_result(
        json.dumps(
            result_event(
                result="done",
                session_id="session",
                total_cost_usd=0.012,
                usage={
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "cache_read_input_tokens": 60,
                    "cache_creation_input_tokens": 20,
                    "reasoning_tokens": 5,
                },
            )
        )
    )
    assert result.status == "success"
    assert result.summary == "done"
    assert result.session_id == "session"
    assert result.usage == Usage(
        input_tokens=100,
        output_tokens=10,
        cached_input_tokens=60,
        cache_creation_input_tokens=20,
        cost_usd=0.012,
        cost_source="client_estimate",
        source="provider",
    )
    assert not ClaudeProvider.capabilities.cost_reporting
    assert not ClaudeProvider.capabilities.tool_execution
    assert Usage.model_validate_json('{"input_tokens":1,"source":"provider"}').cost_source == (
        "unknown"
    )
    missing = parse_result(json.dumps(result_event()))
    assert missing.usage == Usage()
    assert parse_result(json.dumps(result_event(usage={}))).usage.source == "unknown"


@pytest.mark.parametrize("stdout", ["", "not json", "[]", "null", "{}", "{}\n{}"])
def test_rejects_invalid_transport(stdout: str) -> None:
    assert parse_result(stdout).error_kind == "malformed_output"


def test_nullable_sdk_fields_preserve_error_usage() -> None:
    parsed = parse_result(
        json.dumps(
            result_event(
                result=None,
                errors=None,
                permission_denials=None,
                api_error_status=401,
                is_error=True,
                usage={"input_tokens": 0},
            )
        ),
        1,
    )
    assert parsed.error_kind == "authentication"
    assert parsed.usage.input_tokens == 0
    assert parsed.usage.source == "provider"


def test_oversized_numeric_cost_is_normalized() -> None:
    assert (
        parse_result(
            json.dumps(
                result_event(
                    total_cost_usd=10**400,
                )
            )
        ).error_kind
        == "malformed_output"
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"type": "assistant"},
        {"subtype": None},
        {"subtype": ""},
        {"is_error": 0},
        {"is_error": "false"},
        {"is_error": None},
        {"result": {}},
        {"session_id": 1},
        {"errors": "error"},
        {"errors": [1]},
        {"permission_denials": {}},
        {"permission_denials": ["Edit"]},
        {"usage": []},
        {"usage": {"input_tokens": True}},
        {"usage": {"output_tokens": "1"}},
        {"usage": {"input_tokens": -1}},
        {"usage": {"cache_read_input_tokens": 1.5}},
        {"usage": {"cache_creation_input_tokens": False}},
        {"total_cost_usd": "0.1"},
        {"total_cost_usd": True},
        {"total_cost_usd": -1},
        {"total_cost_usd": float("inf")},
        {"total_cost_usd": float("nan")},
        {"api_error_status": True},
        {"api_error_status": "401"},
        {"api_error_status": 999},
    ],
)
def test_rejects_malformed_result_fields(fields: dict[str, Any]) -> None:
    assert parse_result(json.dumps(result_event(**fields))).error_kind == "malformed_output"


@pytest.mark.parametrize(
    ("fields", "exit_code", "kind"),
    [
        ({"is_error": True}, 0, "provider_error"),
        ({"subtype": "error_max_turns"}, 0, "provider_error"),
        ({"errors": ["failed"]}, 0, "provider_error"),
        ({"is_error": True, "errors": ["Unauthorized 401"]}, 1, "authentication"),
        ({"permission_denials": [{"tool_name": "Edit"}]}, 0, "permission_denied"),
        ({}, 1, "exit_code"),
        ({}, None, "exit_code"),
        ({"api_error_status": 401}, 1, "authentication"),
        ({"api_error_status": 403}, 0, "authentication"),
        ({"api_error_status": 500}, 1, "provider_error"),
    ],
)
def test_failures_retain_usage(fields: dict[str, Any], exit_code: int | None, kind: str) -> None:
    parsed = parse_result(
        json.dumps(
            result_event(
                usage={"output_tokens": 2},
                total_cost_usd=0,
                **fields,
            )
        ),
        exit_code,
    )
    assert parsed.status == "error"
    assert parsed.error_kind == kind
    assert parsed.usage.output_tokens == 2
    assert parsed.usage.cost_usd == 0
    assert parsed.usage.cost_source == "client_estimate"


@pytest.mark.parametrize("shim", ["claude.cmd", "claude.ps1", "claude.bat"])
def test_resolver_prefers_native_npm_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shim: str,
) -> None:
    native = tmp_path / "node_modules/@anthropic-ai/claude-code/bin/claude.exe"
    native.parent.mkdir(parents=True)
    native.touch()
    monkeypatch.setattr("eng.providers.claude.shutil.which", lambda _: str(tmp_path / shim))
    assert claude_command() == [str(native)]


def test_resolver_supports_only_existing_legacy_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = tmp_path / "node_modules/@anthropic-ai/claude-code/cli.js"
    legacy.parent.mkdir(parents=True)
    legacy.touch()
    monkeypatch.setattr(
        "eng.providers.claude.shutil.which",
        lambda name: str(tmp_path / "claude.cmd") if name == "claude" else "node.exe",
    )
    assert claude_command() == ["node.exe", str(legacy)]
    legacy.unlink()
    with pytest.raises(ValueError, match="Cannot resolve"):
        claude_command()


def test_missing_cli_and_legacy_node(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("eng.providers.claude.shutil.which", lambda _: None)
    with pytest.raises(ValueError, match="not found"):
        claude_command()
    legacy = tmp_path / "node_modules/@anthropic-ai/claude-code/cli.js"
    legacy.parent.mkdir(parents=True)
    legacy.touch()
    monkeypatch.setattr(
        "eng.providers.claude.shutil.which",
        lambda name: str(tmp_path / "claude.cmd") if name == "claude" else None,
    )
    with pytest.raises(ValueError, match="Cannot resolve"):
        claude_command()


def test_native_cli_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("eng.providers.claude.shutil.which", lambda _: "/usr/bin/claude")
    assert claude_command() == ["/usr/bin/claude"]


def test_credentials_are_provider_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    claude = {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CONFIG_DIR",
    }
    codex = {"OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_HOME"}
    other = {"GITHUB_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK", "NODE_OPTIONS"}
    for name in claude | codex | other:
        monkeypatch.setenv(name, "fixture-value")
    assert claude <= clean_environment(provider="claude").keys()
    assert not (codex | other) & clean_environment(provider="claude").keys()
    for selector in (True, "codex"):
        assert codex <= clean_environment(provider=selector).keys()  # type: ignore[arg-type]
        assert not (claude | other) & clean_environment(provider=selector).keys()  # type: ignore[arg-type]
    assert not (claude | codex | other) & clean_environment().keys()


def request(workspace: Path, model: str | None = None) -> ProviderRequest:
    return ProviderRequest(
        task_id="t",
        execution_id="e",
        workspace=workspace,
        prompt="Fix it\nusing stdin",
        timeout_seconds=5,
        model=model,
    )


def test_safe_argv_stdin_and_json_redaction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-test-key")
    monkeypatch.setattr("eng.providers.claude.claude_command", lambda: ["claude.exe"])
    captured: dict[str, Any] = {}

    async def run(argv: list[str], cwd: Path, deadline: float, **kwargs: Any) -> ProcessResult:
        captured.update(argv=argv, cwd=cwd, timeout=deadline, **kwargs)
        return ProcessResult(
            0,
            json.dumps(
                result_event(
                    result='secret-test-key api_key="other-secret"',
                    usage={"input_tokens": 1, "output_tokens": 2},
                    total_cost_usd=0.01,
                )
            ),
            "secret-test-key",
            0.5,
        )

    monkeypatch.setattr("eng.providers.claude.run_process", run)
    provider: Provider = ClaudeProvider()
    output = asyncio.run(
        provider.execute(
            request(tmp_path, "sonnet"),
            tmp_path / "a",
            lambda: False,
        )
    )
    assert captured["argv"] == [
        "claude.exe",
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
        "--model",
        "sonnet",
    ]
    assert captured["cwd"] == tmp_path
    assert captured["stdin"] == request(tmp_path).prompt
    assert captured["provider"] == "claude"
    assert captured["timeout"] == 5
    evidence_text = (tmp_path / "a/provider.json").read_text()
    evidence = json.loads(evidence_text)
    assert "secret-test-key" not in evidence_text
    assert "other-secret" not in evidence_text
    assert evidence["usage"] == {"input_tokens": 1, "output_tokens": 2}
    assert evidence["total_cost_usd"] == 0.01
    assert (tmp_path / "a/provider.stderr.log").read_text() == "[REDACTED]"
    assert output.status == "success"
    assert output.duration_seconds == 0.5
    assert output.usage.output_tokens == 2


@pytest.mark.parametrize(
    ("reason", "status"),
    [
        ("cancelled", "cancelled"),
        ("timeout", "timeout"),
        ("unavailable", "error"),
        ("process_isolation", "error"),
    ],
)
def test_process_failures_are_normalized(
    reason: str,
    status: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("eng.providers.claude.claude_command", lambda: ["claude.exe"])

    async def run(*args: Any, **kwargs: Any) -> ProcessResult:
        return ProcessResult(None, "partial", "stopped", 0.1, reason)

    monkeypatch.setattr("eng.providers.claude.run_process", run)
    output = asyncio.run(ClaudeProvider().execute(request(tmp_path), tmp_path / "a", lambda: True))
    assert output.status == status
    assert output.error_kind == reason
    assert output.summary == "stopped"
    assert (tmp_path / "a/provider.json").read_text() == "partial"


@pytest.mark.parametrize(
    ("stdout", "stderr", "kind"),
    [
        (
            json.dumps(
                result_event(is_error=True, errors=["401 unauthorized"], usage={"output_tokens": 1})
            ),
            "",
            "authentication",
        ),
        ("", "login required", "authentication"),
        ("", "failure", "exit_code"),
        ("bad json", "failure", "malformed_output"),
    ],
)
def test_nonzero_exit_parses_stdout_errors(
    stdout: str,
    stderr: str,
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("eng.providers.claude.claude_command", lambda: ["claude.exe"])

    async def run(*args: Any, **kwargs: Any) -> ProcessResult:
        return ProcessResult(1, stdout, stderr, 0.2)

    monkeypatch.setattr("eng.providers.claude.run_process", run)
    output = asyncio.run(ClaudeProvider().execute(request(tmp_path), tmp_path / "a", lambda: False))
    assert output.status == "error"
    assert output.error_kind == kind
    if stdout.startswith("{"):
        assert output.usage.output_tokens == 1


def test_unavailable_resolver_returns_normalized_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("eng.providers.claude.shutil.which", lambda _: None)
    output = asyncio.run(ClaudeProvider().execute(request(tmp_path), tmp_path / "a", lambda: False))
    assert output.error_kind == "unavailable"

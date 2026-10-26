import asyncio
import sys
from pathlib import Path

import pytest

from eng.core.models import CommandProviderConfig, ProviderRequest
from eng.providers.command import CommandProvider


def request(workspace: Path, *, model: str | None = None, timeout: float = 30) -> ProviderRequest:
    return ProviderRequest(
        task_id="t",
        execution_id="e",
        workspace=workspace,
        prompt="hello prompt",
        timeout_seconds=timeout,
        model=model,
    )


def provider(code: str, **extra: object) -> CommandProvider:
    config = CommandProviderConfig(argv=[sys.executable, "-c", code], **extra)  # type: ignore[arg-type]
    return CommandProvider("scripted", config)


def run(command: CommandProvider, workspace: Path, tmp_path: Path, **options: object) -> object:
    return asyncio.run(
        command.execute(request(workspace, **options), tmp_path / "artifacts", lambda: False)  # type: ignore[arg-type]
    )


def test_success_passes_prompt_on_stdin_and_runs_in_workspace(tmp_path: Path) -> None:
    code = "import sys, pathlib; pathlib.Path('seen.txt').write_text(sys.stdin.read()); print('ok')"
    result = run(provider(code), tmp_path, tmp_path)
    assert result.status == "success" and result.summary.strip() == "ok"  # type: ignore[attr-defined]
    assert (tmp_path / "seen.txt").read_text() == "hello prompt"
    assert result.usage.input_tokens is None and result.usage.cost_source == "unknown"  # type: ignore[attr-defined]
    assert (tmp_path / "artifacts" / "provider.log").is_file()


def test_nonzero_exit_is_an_error_with_redacted_stderr(tmp_path: Path) -> None:
    code = "import sys; print('token=abcdef123456 boom', file=sys.stderr); sys.exit(3)"
    result = run(provider(code), tmp_path, tmp_path)
    assert result.status == "error" and result.error_kind == "exit_code"  # type: ignore[attr-defined]
    assert "abcdef123456" not in result.summary  # type: ignore[attr-defined]


def test_timeout_and_cancellation_map_to_statuses(tmp_path: Path) -> None:
    slow = provider("import time; time.sleep(30)")
    timed = asyncio.run(slow.execute(request(tmp_path, timeout=0.5), tmp_path / "a", lambda: False))
    assert timed.status == "timeout"
    cancelled = asyncio.run(slow.execute(request(tmp_path), tmp_path / "b", lambda: True))
    assert cancelled.status == "cancelled"


def test_missing_executable_is_unavailable(tmp_path: Path) -> None:
    config = CommandProviderConfig(argv=["definitely-not-a-real-cli-xyz"])
    result = asyncio.run(
        CommandProvider("ghost", config).execute(request(tmp_path), tmp_path / "a", lambda: False)
    )
    assert result.status == "error" and result.error_kind == "unavailable"


def test_model_selection_requires_a_declared_flag(tmp_path: Path) -> None:
    refused = run(provider("print('x')"), tmp_path, tmp_path, model="big")
    assert refused.error_kind == "model_unsupported"  # type: ignore[attr-defined]
    code = "import sys; print(' '.join(sys.argv[1:]))"
    config = CommandProviderConfig(argv=[sys.executable, "-c", code], model_flag="--model")
    accepted = run(CommandProvider("scripted", config), tmp_path, tmp_path, model="big")
    assert accepted.status == "success" and accepted.summary.strip() == "--model big"  # type: ignore[attr-defined]


def test_environment_is_scrubbed_except_declared_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNRELATED_API_KEY", "leak-me-please-123")
    monkeypatch.setenv("MYCLI_API_KEY", "forward-me-please-456")
    code = (
        "import os; print(os.environ.get('UNRELATED_API_KEY'), os.environ.get('MYCLI_API_KEY'),"
        " os.environ.get('ENG_ACTIVE'))"
    )
    result = run(provider(code, env_allow=["MYCLI_API_KEY"]), tmp_path, tmp_path)
    # The forwarded value reaches the child but is redacted from every recorded output.
    assert result.summary.strip() == "None [REDACTED] 1"  # type: ignore[attr-defined]
    assert "forward-me-please-456" not in (tmp_path / "artifacts" / "provider.log").read_text()

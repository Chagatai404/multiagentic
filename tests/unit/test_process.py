import asyncio
import os
import sys
from pathlib import Path

from eng.execution.process import clean_environment, redact, redact_data, run_process


def test_timeout_and_cancellation_stop_real_process(tmp_path: Path) -> None:
    result = asyncio.run(
        run_process([sys.executable, "-c", "import time;time.sleep(30)"], tmp_path, 0.3)
    )
    assert result.reason == "timeout"
    assert result.duration_seconds < 10
    result = asyncio.run(
        run_process(
            [sys.executable, "-c", "import time;time.sleep(30)"],
            tmp_path,
            30,
            cancelled=lambda: True,
        )
    )
    assert result.reason == "cancelled"


def test_shell_metacharacters_are_literal_and_output_is_drained(tmp_path: Path) -> None:
    payload = "$(touch hacked); & echo bad"
    result = asyncio.run(
        run_process([sys.executable, "-c", "import sys;print(sys.argv[1])", payload], tmp_path, 10)
    )
    assert result.exit_code == 0
    assert result.stdout.strip() == payload
    assert not (tmp_path / "hacked").exists()
    large = asyncio.run(
        run_process([sys.executable, "-c", "print('x'*1000000)"], tmp_path, 10, output_limit=256)
    )
    assert large.exit_code == 0
    assert len(large.stdout) == 256


def test_missing_executable_and_nonzero_are_distinct(tmp_path: Path) -> None:
    missing = asyncio.run(run_process(["eng-nonexistent-executable-1234"], tmp_path, 10))
    assert missing.reason == "unavailable"
    failed = asyncio.run(run_process([sys.executable, "-c", "raise SystemExit(7)"], tmp_path, 10))
    assert failed.exit_code == 7
    assert failed.reason is None


def test_check_environment_strips_secrets(monkeypatch: object) -> None:
    from pytest import MonkeyPatch

    assert isinstance(monkeypatch, MonkeyPatch)
    monkeypatch.setenv("TEST_API_KEY", "uniquesecret123456")
    monkeypatch.setenv("OPENAI_API_KEY", "providersecret123456")
    assert "TEST_API_KEY" not in clean_environment()
    assert "OPENAI_API_KEY" not in clean_environment()
    assert clean_environment(provider=True)["OPENAI_API_KEY"] == "providersecret123456"
    assert "uniquesecret123456" not in redact("error: uniquesecret123456")
    assert "abc123" not in redact("Authorization: Bearer abc123")
    assert "hiddenvalue" not in redact('api_key="hiddenvalue"')
    assert "PATH" in {key.upper() for key in os.environ}


def test_redaction_preserves_usage_and_json_shape() -> None:
    import json

    data = {"input_tokens": 100, "output_tokens": None, "summary": 'api_key="hiddenvalue"'}
    cleaned = redact_data(data)
    assert json.loads(json.dumps(cleaned))["input_tokens"] == 100
    assert cleaned["output_tokens"] is None
    assert "hiddenvalue" not in cleaned["summary"]
    assert '"input_tokens": 100' in redact(json.dumps({"input_tokens": 100}))


def test_timeout_kills_descendant_even_when_parent_exits(tmp_path: Path) -> None:
    """An inherited pipe must not keep communicate alive after its parent has exited."""
    import time

    marker = tmp_path / "escaped.txt"
    child = (
        "import time; from pathlib import Path; time.sleep(2); "
        f"Path({str(marker)!r}).write_text('escaped')"
    )
    parent = (
        "import subprocess,sys,time; time.sleep(0.2); "
        f"subprocess.Popen([sys.executable, '-c', {child!r}])"
    )
    result = asyncio.run(run_process([sys.executable, "-c", parent], tmp_path, 0.8))
    assert result.reason == "timeout"
    assert result.duration_seconds < 5
    time.sleep(2.2)
    assert not marker.exists()

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from eng.execution import process
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows job startup race")
@pytest.mark.parametrize("exit_code", [0, 7])
def test_short_child_waits_for_job_assignment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int
) -> None:
    marker = tmp_path / "ran.txt"
    ran_before_assignment = []
    real_job = process.WindowsJob

    class DelayedJob(real_job):
        def __init__(self, pid: int) -> None:
            # Deterministically expose the old spawn/attach race, even on an idle host.
            time.sleep(0.5)
            ran_before_assignment.append(marker.exists())
            super().__init__(pid)

    monkeypatch.setattr(process, "WindowsJob", DelayedJob)
    script = (
        "import sys; from pathlib import Path; "
        f"Path({str(marker)!r}).write_text('ran'); print('captured'); sys.exit({exit_code})"
    )
    result = asyncio.run(run_process([sys.executable, "-c", script], tmp_path, 10))
    assert result.reason is None, result
    assert result.exit_code == exit_code
    assert result.stdout.strip() == "captured"
    assert ran_before_assignment == [False]
    assert marker.read_text() == "ran"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows suspended-child cleanup")
def test_resume_failure_closes_job_without_running_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "must-not-run.txt"
    jobs = []
    real_job = process.WindowsJob

    class BrokenResumeJob(real_job):
        def resume(self, pid: int) -> None:
            jobs.append(self)
            raise OSError("injected ResumeThread failure")

    monkeypatch.setattr(process, "WindowsJob", BrokenResumeJob)
    script = f"from pathlib import Path; Path({str(marker)!r}).write_text('escaped')"
    result = asyncio.run(run_process([sys.executable, "-c", script], tmp_path, 10))
    assert result.reason == "process_isolation", result
    assert "injected ResumeThread failure" in result.stderr
    assert len(jobs) == 1 and jobs[0].handle is None
    assert not marker.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows suspended-child cleanup")
def test_job_assignment_failure_does_not_run_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "must-not-run.txt"

    def refuse_job(pid: int) -> None:
        raise OSError("injected job assignment failure")

    monkeypatch.setattr(process, "WindowsJob", refuse_job)
    script = f"from pathlib import Path; Path({str(marker)!r}).write_text('escaped')"
    result = asyncio.run(run_process([sys.executable, "-c", script], tmp_path, 10))
    assert result.reason == "process_isolation", result
    assert "injected job assignment failure" in result.stderr
    assert not marker.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows job descendant inheritance")
def test_immediate_descendant_belongs_to_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "escaped.txt"
    real_job = process.WindowsJob

    class DelayedJob(real_job):
        def __init__(self, pid: int) -> None:
            time.sleep(0.5)
            super().__init__(pid)

    monkeypatch.setattr(process, "WindowsJob", DelayedJob)
    child = f"import time; from pathlib import Path; time.sleep(2); Path({str(marker)!r}).touch()"
    parent = f"import subprocess,sys; subprocess.Popen([sys.executable, '-c', {child!r}])"
    result = asyncio.run(run_process([sys.executable, "-c", parent], tmp_path, 1))
    assert result.reason == "timeout", result
    time.sleep(2.2)
    assert not marker.exists()

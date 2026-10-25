import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from eng.integrations import runner

SRC = Path(__file__).resolve().parents[2] / "src"

# Child: outlives the hook by a wide margin, then writes a marker. The margin is 8 s because
# this host shows multi-second process-startup stalls even for a hook that spawns nothing.
CHILD_LIFETIME = 8.0
CHILD_SLEEP_THEN_MARK = (
    "import pathlib, sys, time\n"
    f"time.sleep({CHILD_LIFETIME})\n"
    "pathlib.Path(sys.argv[1]).write_text('alive', encoding='utf-8')\n"
)

# Hook: spawns the detached child through the runner and exits immediately.
HOOK = (
    "import sys\n"
    "from pathlib import Path\n"
    "from eng.integrations.runner import spawn_detached\n"
    "pid = spawn_detached([sys.executable, sys.argv[1], sys.argv[2]],\n"
    "                     cwd=Path(sys.argv[3]), log_path=Path(sys.argv[4]))\n"
    "assert pid > 0\n"
)


def _wait_for(predicate: Callable[[], bool], timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_hook_returns_before_detached_child_and_child_survives(tmp_path: Path) -> None:
    child = tmp_path / "child.py"
    child.write_text(CHILD_SLEEP_THEN_MARK, encoding="utf-8")
    marker = tmp_path / "marker.txt"
    log = tmp_path / "logs" / "child.log"
    env = {**os.environ, "PYTHONPATH": str(SRC)}

    started = time.monotonic()
    # Captured pipes: a child holding them would make run() wait for its whole lifetime.
    hook = subprocess.run(
        [sys.executable, "-c", HOOK, str(child), str(marker), str(tmp_path), str(log)],
        capture_output=True,
        env=env,
        cwd=tmp_path,
        timeout=30,
        check=False,
    )
    elapsed = time.monotonic() - started

    assert hook.returncode == 0, hook.stderr.decode(errors="replace")
    assert not marker.exists(), "hook returned only after the child finished (pipes held)"
    assert elapsed < CHILD_LIFETIME - 1, f"hook waited for the child ({elapsed:.2f}s)"
    assert _wait_for(marker.exists, timeout=CHILD_LIFETIME + 5), "child did not survive"
    assert marker.read_text(encoding="utf-8") == "alive"


def test_child_output_is_appended_to_log(tmp_path: Path) -> None:
    script = "import sys; print('out-line'); print('err-line', file=sys.stderr)"
    log = tmp_path / "nested" / "child.log"
    log.parent.mkdir()
    log.write_text("existing\n", encoding="utf-8")

    runner.spawn_detached([sys.executable, "-c", script], cwd=tmp_path, log_path=log)
    runner.spawn_detached([sys.executable, "-c", script], cwd=tmp_path, log_path=log)

    def complete() -> bool:
        text = _read(log)
        return text.count("out-line") == 2 and text.count("err-line") == 2

    assert _wait_for(complete)
    text = _read(log)
    assert text.startswith("existing\n")
    assert text.count("out-line") == 2
    assert text.count("err-line") == 2


def test_env_is_passed_exactly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENG_RUNNER_ABSENT", "must-not-leak")
    script = (
        "import os\n"
        "print('CHOSEN=' + str(os.environ.get('ENG_RUNNER_CHOSEN')))\n"
        "print('ABSENT=' + str(os.environ.get('ENG_RUNNER_ABSENT')))\n"
    )
    # Only the Windows loader variables are kept so the child interpreter can start.
    base = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ}
    log = tmp_path / "env.log"

    runner.spawn_detached(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        log_path=log,
        env={**base, "ENG_RUNNER_CHOSEN": "chosen-value"},
    )

    assert _wait_for(lambda: "ABSENT=" in _read(log))
    lines = _read(log).splitlines()
    assert "CHOSEN=chosen-value" in lines
    assert "ABSENT=None" in lines


def test_missing_executable_raises_oserror(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        runner.spawn_detached(
            [str(tmp_path / "no-such-executable-eng")],
            cwd=tmp_path,
            log_path=tmp_path / "missing.log",
        )


def test_empty_argv_raises_oserror(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        runner.spawn_detached([], cwd=tmp_path, log_path=tmp_path / "empty.log")


@pytest.mark.skipif(sys.platform != "win32", reason="job breakaway is Windows-only")
def test_refused_breakaway_retries_without_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_popen = subprocess.Popen
    flags_seen: list[int] = []

    def refuse_breakaway(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        flags = int(kwargs.get("creationflags", 0))
        flags_seen.append(flags)
        if flags & runner._CREATE_BREAKAWAY_FROM_JOB:
            # What CreateProcess reports when the parent job forbids breakaway.
            raise PermissionError(5, "Access is denied")
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", refuse_breakaway)
    marker = tmp_path / "fallback.txt"
    script = "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text('ok', encoding='utf-8')"

    pid = runner.spawn_detached(
        [sys.executable, "-c", script, str(marker)],
        cwd=tmp_path,
        log_path=tmp_path / "fallback.log",
    )

    assert pid > 0
    assert len(flags_seen) == 2
    assert flags_seen[0] & runner._CREATE_BREAKAWAY_FROM_JOB
    assert not flags_seen[1] & runner._CREATE_BREAKAWAY_FROM_JOB
    assert _wait_for(marker.exists)

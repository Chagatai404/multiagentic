"""End-to-end trigger flow through real hook subprocesses and detached runners.

Client input is emulated; no live Claude Code or Codex hook is fired.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from eng.cli import app
from eng.core.models import State, Task
from eng.core.policy import TERMINAL
from eng.storage.store import Store

runner = CliRunner()


def hook(
    repo: Path,
    payload: object,
    *arguments: str,
    env: dict[str, str] | None = None,
    client: str = "claude-code",
) -> tuple[int, str, float]:
    environment = {k: v for k, v in os.environ.items() if k != "ENG_ACTIVE"}
    environment.update(env or {})
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "eng.integrations.hook", client, *arguments],
        input=raw.encode("utf-8"),
        capture_output=True,
        cwd=repo,
        env=environment,
        timeout=60,
        check=False,
    )
    return result.returncode, result.stdout.decode("utf-8"), time.monotonic() - started


def claude_payload(repo: Path, prompt: str, prompt_id: str | None = "p-1") -> dict[str, str]:
    payload = {
        "session_id": "s-1",
        "transcript_path": str(repo / "transcript.jsonl"),
        "cwd": str(repo),
        "permission_mode": "default",
        "hook_event_name": "UserPromptSubmit",
        "prompt": prompt,
    }
    if prompt_id:
        payload["prompt_id"] = prompt_id
    return payload


def tasks(repo: Path) -> list[Task]:
    store = Store(repo)
    try:
        return store.list_tasks()
    finally:
        store.close()


def wait_for_runner(repo: Path, task_id: str, seconds: float = 120) -> Task:
    deadline = time.monotonic() + seconds
    while True:
        store = Store(repo)
        try:
            task = store.load(task_id)
        finally:
            store.close()
        if task.state in TERMINAL or task.state in {State.BLOCKED, State.PAUSED}:
            return task
        if time.monotonic() > deadline:
            pytest.fail(f"Detached runner did not finish; state {task.state}")
        time.sleep(0.5)


def test_explicit_request_routes_once_and_detached_runner_executes(repo: Path) -> None:
    payload = claude_payload(repo, "eng: fix the answer file")
    code, output, elapsed = hook(repo, payload, "--mode", "manual", "--provider", "fake")
    assert code == 0 and elapsed < 15
    decision = json.loads(output)
    assert decision["decision"] == "block"
    [task] = tasks(repo)
    assert task.id in decision["reason"] and task.spec.description == "fix the answer file"
    # Redelivery of the same prompt id is idempotent: same task, no second runner.
    code, output, _ = hook(repo, payload, "--mode", "manual", "--provider", "fake")
    assert code == 0 and task.id in json.loads(output)["reason"]
    assert [t.id for t in tasks(repo)] == [task.id]
    finished = wait_for_runner(repo, task.id)
    # The fake provider makes no edit, so the real configured check fails and blocks.
    assert finished.state == State.BLOCKED, finished.message
    assert finished.provider_calls == 1
    assert finished.verification[0].outcome == "FAIL"
    log = repo / ".engineering" / "artifacts" / task.id / "runner.log"
    assert log.is_file()


@pytest.mark.parametrize(
    ("prompt", "mode"),
    [
        ("How does the answer check work?", "adaptive"),
        ("Fix the failing answer check", "manual"),
        ("/review the diff", "adaptive"),
        ("thanks, looks good", "adaptive"),
    ],
)
def test_non_routed_prompts_pass_through_untouched(repo: Path, prompt: str, mode: str) -> None:
    code, output, _ = hook(repo, claude_payload(repo, prompt), "--mode", mode)
    assert (code, output) == (0, "")
    assert tasks(repo) == []


def test_adaptive_imperative_routes_for_codex(repo: Path) -> None:
    payload = {
        "session_id": "thr_1",
        "turn_id": "turn_1",
        "transcript_path": None,
        "cwd": str(repo),
        "hook_event_name": "UserPromptSubmit",
        "model": "gpt-test",
        "permission_mode": "default",
        "prompt": "Fix the failing answer check",
    }
    code, output, _ = hook(
        repo, payload, "--mode", "adaptive", "--provider", "fake", client="codex"
    )
    assert code == 0 and json.loads(output)["decision"] == "block"
    [task] = tasks(repo)
    wait_for_runner(repo, task.id)


def test_reentrant_hook_inside_eng_never_routes(repo: Path) -> None:
    code, output, _ = hook(
        repo,
        claude_payload(repo, "eng: fix the answer file"),
        "--mode",
        "adaptive",
        env={"ENG_ACTIVE": "1"},
    )
    assert (code, output) == (0, "")
    assert tasks(repo) == []


@pytest.mark.parametrize(
    ("payload", "arguments", "client"),
    [
        ("", ("--mode", "adaptive"), "claude-code"),
        ("{not json", ("--mode", "adaptive"), "claude-code"),
        ('["list"]', (), "codex"),
        ('{"cwd": "."}', (), "claude-code"),
        ("{}", ("--bogus", "--mode"), "unknown-client"),
        ("{}", ("--mode", "nonsense"), "claude-code"),
    ],
)
def test_hook_failures_never_block_the_prompt(
    repo: Path, payload: str, arguments: tuple[str, ...], client: str
) -> None:
    code, output, _ = hook(repo, payload, *arguments, client=client)
    assert code == 0  # exit code 2 would block the user's prompt in both clients
    assert "systemMessage" in json.loads(output)
    assert tasks(repo) == []


def test_unknown_provider_and_non_repository_fail_open(repo: Path, tmp_path: Path) -> None:
    code, output, _ = hook(
        repo, claude_payload(repo, "eng: fix it"), "--provider", "no-such-provider"
    )
    assert code == 0 and "systemMessage" in json.loads(output)
    outside = tmp_path / "plain"
    outside.mkdir()
    code, output, _ = hook(outside, claude_payload(outside, "eng: fix it"))
    assert code == 0 and "systemMessage" in json.loads(output)
    assert tasks(repo) == []


def test_dirty_checkout_fails_open_before_recording(repo: Path) -> None:
    (repo / "answer.txt").write_text("local edit", encoding="utf-8")
    code, output, _ = hook(repo, claude_payload(repo, "eng: fix the answer file"))
    assert code == 0 and "uncommitted" in json.loads(output)["systemMessage"]
    assert tasks(repo) == []


def test_dirty_checkout_heuristic_prompts_pass_through_silently(repo: Path) -> None:
    (repo / "answer.txt").write_text("local edit", encoding="utf-8")
    code, output, _ = hook(
        repo, claude_payload(repo, "Fix the failing answer check"), "--mode", "adaptive"
    )
    assert (code, output) == (0, "")
    assert tasks(repo) == []


def test_hook_bound_to_another_project_bypasses(repo: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    code, output, _ = hook(
        repo, claude_payload(repo, "eng: fix the answer file"), "--project", str(other)
    )
    assert (code, output) == (0, "")
    assert tasks(repo) == []


def test_unignored_runtime_state_fails_open_without_state(repo: Path) -> None:
    (repo / ".gitignore").write_text("", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Eng Test",
            "-c",
            "user.email=eng@example.invalid",
            "commit",
            "-m",
            "unignore",
        ],
        check=True,
        capture_output=True,
    )
    code, output, _ = hook(repo, claude_payload(repo, "eng: fix the answer file"))
    assert code == 0 and "not ignored" in json.loads(output)["systemMessage"]
    assert not (repo / ".engineering" / "state").exists()


def test_cli_trigger_listing_keeps_no_raw_prompt(repo: Path) -> None:
    secret = "API_KEY=sk-test-1234567890"
    result = runner.invoke(
        app,
        ["trigger", f"eng: fix the answer file {secret}", "-p", str(repo), "--provider", "fake"],
    )
    assert result.exit_code == 0, result.output
    decision = json.loads(result.output)
    assert decision["action"] == "route" and decision["task_id"]
    listing = runner.invoke(app, ["triggers", "-p", str(repo)])
    assert listing.exit_code == 0 and "sk-test-1234567890" not in listing.output
    [record] = json.loads(listing.output)
    assert record["task_id"] == decision["task_id"] and record["status"] == "started"
    wait_for_runner(repo, decision["task_id"])


def test_installed_claude_hook_command_runs_and_uninstalls(repo: Path) -> None:
    result = runner.invoke(
        app,
        [
            "hooks",
            "install",
            "claude-code",
            "-p",
            str(repo),
            "--mode",
            "adaptive",
            "--provider",
            "fake",
        ],
    )
    assert result.exit_code == 0, result.output
    settings = json.loads((repo / ".claude" / "settings.local.json").read_text("utf-8"))
    [group] = settings["hooks"]["UserPromptSubmit"]
    [entry] = group["hooks"]
    assert entry["timeout"] <= 30 and "eng.integrations.hook" in entry["args"]
    assert entry["args"][-2:] == ["--project", str(repo.resolve())]
    # The per-user hook file is excluded locally, so routing still sees a clean checkout.
    status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, check=True
    )
    assert status.stdout == b""

    def client(prompt: str, prompt_id: str) -> subprocess.CompletedProcess[bytes]:
        # Execute exactly what the client would run (exec form, no shell).
        return subprocess.run(
            [entry["command"], *entry["args"]],
            input=json.dumps(claude_payload(repo, prompt, prompt_id)).encode(),
            capture_output=True,
            cwd=repo,
            timeout=60,
            check=False,
        )

    question = client("What does check.py verify?", "p-q")
    assert (question.returncode, question.stdout) == (0, b"")
    routed = client("Fix the failing answer check", "p-r")
    assert routed.returncode == 0 and json.loads(routed.stdout)["decision"] == "block"
    [task] = tasks(repo)
    wait_for_runner(repo, task.id)
    status = runner.invoke(app, ["hooks", "status", "claude-code", "-p", str(repo)])
    assert json.loads(status.output)["installed"] is True
    removed = runner.invoke(app, ["hooks", "uninstall", "claude-code", "-p", str(repo)])
    assert removed.exit_code == 0
    status = runner.invoke(app, ["hooks", "status", "claude-code", "-p", str(repo)])
    assert json.loads(status.output)["installed"] is False


def test_start_refuses_started_tasks_and_nested_execution(repo: Path) -> None:
    result = runner.invoke(
        app, ["trigger", "eng: fix the answer file", "-p", str(repo), "--provider", "fake"]
    )
    task_id = json.loads(result.output)["task_id"]
    wait_for_runner(repo, task_id)
    again = runner.invoke(app, ["start", task_id, "-p", str(repo)])
    assert again.exit_code == 2 and "already started" in again.output
    nested = runner.invoke(app, ["start", task_id, "-p", str(repo)], env={"ENG_ACTIVE": "1"})
    assert nested.exit_code == 2 and "Nested" in nested.output

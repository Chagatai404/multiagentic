import json
from pathlib import Path

from typer.testing import CliRunner

from eng.cli import app

runner = CliRunner()


def test_cli_run_inspect_cancel_terminal_and_bad_provider(repo: Path) -> None:
    run = runner.invoke(
        app,
        [
            "run",
            "fix answer",
            "--accept",
            "answer is 42",
            "--provider",
            "fake",
            "--fake-change",
            "answer.txt=42",
            "-p",
            str(repo),
        ],
    )
    assert run.exit_code == 0, run.output
    task = json.loads(run.output)
    assert task["state"] == "COMPLETED"
    status = runner.invoke(app, ["status", task["id"], "-p", str(repo)])
    assert status.exit_code == 0
    assert json.loads(status.output)["task"]["state"] == "COMPLETED"
    cancel = runner.invoke(app, ["cancel", task["id"], "-p", str(repo)])
    assert not json.loads(cancel.output)["cancellation_requested"]
    bad = runner.invoke(
        app, ["run", "fix", "--accept", "works", "--provider", "unknown", "-p", str(repo)]
    )
    assert bad.exit_code == 2
    assert "Unknown provider" in bad.output


def test_cli_failure_has_nonzero_exit_and_missing_task_actionable(repo: Path) -> None:
    result = runner.invoke(
        app, ["run", "fix", "--accept", "works", "--provider", "fake", "-p", str(repo)]
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["state"] == "BLOCKED"
    missing = runner.invoke(app, ["status", "does-not-exist", "-p", str(repo)])
    assert missing.exit_code == 2
    assert "Task not found" in missing.output

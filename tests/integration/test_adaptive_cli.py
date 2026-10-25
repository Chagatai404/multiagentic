import json
from pathlib import Path

from typer.testing import CliRunner

from eng.cli import app
from eng.core.models import State
from eng.storage.store import Store

runner = CliRunner()


def test_cli_classification_and_budget_overrides_are_persisted(repo: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "Fix answer",
            "--accept",
            "answer is 42",
            "-p",
            str(repo),
            "--provider",
            "fake",
            "--fake-change",
            "answer.txt=42",
            "--complexity",
            "complex",
            "--model-calls",
            "3",
            "--max-repairs",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    task = json.loads(result.output)
    assert task["state"] == "COMPLETED"
    assert task["provider_calls"] == 3 and task["workflow"]["max_repairs"] == 1
    assert task["classification"]["complexity"] == "complex"


def test_cli_saved_approval_and_model_budget_extension(repo: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "Fix answer",
            "--accept",
            "answer is 42",
            "-p",
            str(repo),
            "--provider",
            "fake",
            "--risk",
            "high",
        ],
    )
    assert result.exit_code == 1, result.output
    task = json.loads(result.output)
    assert task["state"] == "PAUSED" and task["workspace"] is None
    resumed = runner.invoke(
        app,
        [
            "resume",
            task["id"],
            "-p",
            str(repo),
            "--approve-high-risk",
            "--extend-model-calls",
            "2",
        ],
    )
    assert resumed.exit_code == 1, resumed.output
    store = Store(repo)
    persisted = store.load(task["id"])
    assert persisted.spec.human_approved and persisted.spec.budgets.model_calls == 3
    assert persisted.state == State.BLOCKED
    assert any(event["kind"] == "human_approved" for event in store.events(task["id"]))
    store.close()


def test_cli_explicit_question_uses_no_workspace_or_calls(repo: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "Explain this code",
            "--accept",
            "understanding",
            "-p",
            str(repo),
            "--provider",
            "fake",
            "--task-type",
            "question",
            "--model-calls",
            "5",
        ],
    )
    assert result.exit_code == 1, result.output
    task = json.loads(result.output)
    assert task["state"] == "BLOCKED" and task["provider_calls"] == 0
    assert task["workspace"] is None

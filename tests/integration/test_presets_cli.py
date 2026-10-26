"""E5: presets through `eng run`, plan creation, preview and node launch."""

import json
from pathlib import Path
from typing import Any

import yaml
from typer.testing import CliRunner

from eng.cli import app
from eng.core.models import State
from eng.core.plan import NodeStatus, PlanSpec
from eng.providers.fake import FakeProvider
from eng.scheduling.runner import PlanRunner
from eng.storage.store import Store

cli = CliRunner()


def run(repo: Path, *options: str) -> dict[str, Any]:
    arguments = ["run", "Fix the answer", "--accept", "42", "-p", str(repo)]
    result = cli.invoke(app, [*arguments, "--provider", "fake", *options])
    document: dict[str, Any] = json.loads(result.output)
    return document


def test_run_preset_resolves_budget_and_workflow_and_explicit_options_win(repo: Path) -> None:
    task = run(repo, "--preset", "balanced", "--risk", "medium")
    spec, config = task["spec"], task["config"]
    assert spec["preset"] == "balanced"
    # Engineer and required review, plus one repair with its re-review.
    assert spec["budgets"]["model_calls"] == 4
    assert spec["budgets"]["context_chars"] == 16000
    workflow = config["workflow"]
    assert workflow == {"max_repairs": 1, "repair_headroom": True, "stop_unchanged_repairs": True}
    explicit = run(repo, "--preset", "economy", "--model-calls", "6", "--max-repairs", "2")
    assert explicit["spec"]["budgets"]["model_calls"] == 6
    assert explicit["config"]["workflow"]["max_repairs"] == 2
    assert explicit["config"]["workflow"]["repair_headroom"] is True
    plain = run(repo)
    assert plain["spec"]["preset"] is None
    assert plain["config"]["workflow"]["repair_headroom"] is False


def test_economy_run_completes_a_clean_change(repo: Path) -> None:
    task = run(repo, "--preset", "economy", "--fake-change", "answer.txt=42")
    assert task["state"] == State.COMPLETED.value and task["provider_calls"] == 1


def test_plan_preset_is_frozen_previewed_and_applied_at_launch(plan_repo: Path) -> None:
    spec = PlanSpec.model_validate(
        {
            "name": "presets",
            "provider": "fake",
            "preset": "economy",
            "nodes": [
                {
                    "id": "a",
                    "description": "Add a",
                    "acceptance": ["ok"],
                    "owns": ["files/a.txt"],
                }
            ],
        }
    )
    path = plan_repo.parent / "plan.yaml"
    path.write_text(yaml.safe_dump(spec.model_dump(mode="json", exclude_none=True)), "utf-8")
    preview = cli.invoke(app, ["plan", "preview", str(path), "-p", str(plan_repo)])
    assert preview.exit_code == 0, preview.output
    document = json.loads(preview.output)
    assert document["preset"] == "economy"
    (node,) = document["nodes"]
    assert node["effective_max_repairs"] == 0 and node["repair_headroom"] is True
    assert node["effective_budgets"]["model_calls"] == 1

    store = Store(plan_repo)
    runner = PlanRunner(plan_repo, lambda name, config: FakeProvider({"files/a.txt": "A"}))
    created = runner.create(store, spec)
    assert created.nodes[0].effective_workflow is not None
    assert created.nodes[0].effective_workflow.stop_unchanged_repairs
    finished = runner.run(created.id)
    assert finished.nodes[0].status == NodeStatus.INTEGRATED
    task = store.load(finished.nodes[0].task_id or "")
    assert task.spec.preset == "economy" and task.config.workflow.repair_headroom
    assert task.config.workflow.max_repairs == 0

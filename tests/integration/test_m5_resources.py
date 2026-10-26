import asyncio
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from eng.agents import execute_role
from eng.cli import app
from eng.core.engine import Engine
from eng.core.models import (
    Budgets,
    ClassificationOverrides,
    Complexity,
    ProviderRequest,
    ProviderResult,
    Role,
    State,
    Task,
    TaskSpec,
    Usage,
)
from eng.projects.config import load_config
from eng.providers.fake import FakeProvider
from eng.storage.store import MIGRATIONS, Store


class Metered(FakeProvider):
    def __init__(
        self, store: Store, usage: Usage, *, changes: dict[str, str] | None = None
    ) -> None:
        super().__init__(changes if changes is not None else {"answer.txt": "42"})
        self.store = store
        self.usage = usage
        self.requests: list[ProviderRequest] = []

    async def execute(
        self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
    ) -> ProviderResult:
        self.requests.append(request)
        reserved = self.store.invocations(request.task_id)[-1]
        saved = self.store.load(request.task_id)
        assert reserved.status == "started" and reserved.model == request.model
        assert saved.pending_model == request.model
        result = await super().execute(request, artifact_dir, cancelled)
        return result.model_copy(update={"usage": self.usage, "duration_seconds": 0.25})


def task_for(repo: Path, store: Store, *, complex: bool = True) -> Task:
    task = Task(
        project=repo,
        config=load_config(repo),
        spec=TaskSpec(
            description="Fix answer",
            acceptance=["answer is 42"],
            provider="fake",
            budgets=Budgets(model_calls=5),
            classification_overrides=ClassificationOverrides(
                complexity=Complexity.COMPLEX if complex else None,
            ),
        ),
    )
    store.create(task)
    return task


def test_routed_models_reserved_before_effect_and_explicit_override(repo: Path) -> None:
    store = Store(repo)
    task = task_for(repo, store)
    task.config.role_models = {Role.PLANNER: "plan", Role.ENGINEER: "edit", Role.REVIEWER: "review"}
    task.spec.budgets.reported_input_tokens = 10
    store.checkpoint(task)
    provider = Metered(store, Usage(input_tokens=10, output_tokens=5))
    paused = asyncio.run(Engine(store, provider, context_cache_enabled=True).execute(task.id))
    assert paused.state == State.PAUSED and paused.checkpoint == "planned"
    assert [request.model for request in provider.requests] == ["plan"]
    paused.spec.model = "explicit"
    paused.spec.budgets.reported_input_tokens = 30
    store.checkpoint(paused)
    completed = asyncio.run(Engine(store, provider).execute(task.id, resume=True))
    assert completed.state == State.COMPLETED, completed.message
    assert [request.model for request in provider.requests] == ["plan", "explicit", "explicit"]
    assert [row.model for row in store.invocations(task.id)] == ["plan", "explicit", "explicit"]
    assert completed.usage == provider.usage  # latest usage remains the result, not a sum
    context = [
        json.loads(event["payload"])
        for event in store.events(task.id)
        if event["kind"] == "context"
    ]
    assert context[0]["cache_enabled"] and context[0]["cache"] is not None
    elapsed = [
        json.loads(event["payload"])
        for event in store.events(task.id)
        if event["kind"] == "role_elapsed"
    ]
    assert len(elapsed) == 3 and elapsed[0]["provider_duration_seconds"] == 0.25
    store.close()


def test_unknown_usage_pauses_before_next_role_and_cli_clear_limit_is_explicit(repo: Path) -> None:
    store = Store(repo)
    task = task_for(repo, store)
    task.spec.budgets.reported_output_tokens = 100
    store.checkpoint(task)
    provider = Metered(store, Usage())
    paused = asyncio.run(Engine(store, provider).execute(task.id))
    assert paused.state == State.PAUSED and len(provider.requests) == 1
    assert "coverage unknown" in paused.message
    store.close()
    runner = CliRunner()
    report = runner.invoke(app, ["usage", task.id, "-p", str(repo)])
    assert report.exit_code == 0, report.output
    parsed = json.loads(report.output)
    assert parsed["invocations"] == 1
    assert parsed["groups"][0]["fields"]["output_tokens"]["known_subtotal"] is None
    resumed = runner.invoke(app, ["resume", task.id, "-p", str(repo), "--clear-reported-limits"])
    assert resumed.exit_code == 1, resumed.output  # Fake default cannot edit answer.
    store = Store(repo)
    saved = store.load(task.id)
    assert saved.spec.budgets.reported_output_tokens is None
    extensions = [
        json.loads(event["payload"])
        for event in store.events(task.id)
        if event["kind"] == "budget_extended"
    ]
    assert extensions[-1]["reported_limits_cleared"] is True
    store.close()


@pytest.mark.parametrize("known", [True, False])
def test_final_call_can_exceed_threshold_and_still_verify_and_complete(
    repo: Path, known: bool
) -> None:
    store = Store(repo)
    task = task_for(repo, store, complex=False)
    task.spec.budgets.reported_input_tokens = 1
    store.checkpoint(task)
    provider = Metered(store, Usage(input_tokens=100) if known else Usage())
    completed = asyncio.run(Engine(store, provider).execute(task.id))
    assert completed.state == State.COMPLETED, completed.message
    assert completed.verification[0].outcome == "PASS" and len(provider.requests) == 1
    store.close()


def test_resume_pending_debugger_escalates_manual_paths_before_call(repo: Path) -> None:
    store = Store(repo)
    task = task_for(repo, store, complex=False)
    task.spec.budgets.reported_input_tokens = 1
    store.checkpoint(task)
    provider = Metered(store, Usage(input_tokens=1), changes={"answer.txt": "wrong"})
    paused = asyncio.run(Engine(store, provider).execute(task.id))
    assert paused.state == State.PAUSED and paused.next_role == Role.DEBUGGER
    assert paused.workspace is not None
    (paused.workspace / "auth.py").write_text("# security boundary\n", encoding="utf-8")
    paused.spec.budgets.reported_input_tokens = 3
    store.checkpoint(paused)
    resumed = asyncio.run(Engine(store, provider).execute(task.id, resume=True))
    assert resumed.state == State.PAUSED and len(provider.requests) == 1
    assert "approve-high-risk" in resumed.message
    store.close()


def test_verify_only_preserves_pending_review_despite_reported_limit(repo: Path) -> None:
    store = Store(repo)
    task = task_for(repo, store)
    task.spec.budgets.reported_input_tokens = 20
    store.checkpoint(task)
    provider = Metered(store, Usage(input_tokens=10))
    paused = asyncio.run(Engine(store, provider).execute(task.id))
    assert paused.state == State.PAUSED and paused.next_role == Role.REVIEWER
    assert len(provider.requests) == 2
    verified = asyncio.run(Engine(store, provider).execute(task.id, resume=True, verify_only=True))
    assert verified.state == State.PAUSED and verified.next_role == Role.REVIEWER
    assert verified.verification[0].outcome == "PASS" and len(provider.requests) == 2
    assert not verified.review_passed
    store.close()


def test_cli_explicit_reported_extensions_and_validation(repo: Path) -> None:
    store = Store(repo)
    task = task_for(repo, store)
    task.spec.budgets.reported_input_tokens = 1
    task.spec.budgets.reported_output_tokens = 2
    task.spec.budgets.reported_cost_usd = 0.1
    store.checkpoint(task)
    provider = Metered(
        store, Usage(input_tokens=1, output_tokens=2, cost_usd=0.1, cost_source="reported")
    )
    paused = asyncio.run(Engine(store, provider).execute(task.id))
    assert paused.state == State.PAUSED
    store.close()
    runner = CliRunner()
    extended = runner.invoke(
        app,
        [
            "resume",
            task.id,
            "-p",
            str(repo),
            "--extend-input-tokens",
            "10",
            "--extend-output-tokens",
            "20",
            "--extend-cost-usd",
            "0.2",
        ],
    )
    assert extended.exit_code == 1, extended.output
    store = Store(repo)
    budget = store.load(task.id).spec.budgets
    assert budget.reported_input_tokens == 11 and budget.reported_output_tokens == 22
    assert budget.reported_cost_usd == 0.3
    assert len(store.invocations(task.id)) == 2  # unknown fake result stops the next call
    store.close()
    rejected = runner.invoke(
        app,
        [
            "resume",
            task.id,
            "-p",
            str(repo),
            "--clear-reported-limits",
            "--extend-input-tokens",
            "1",
        ],
    )
    assert rejected.exit_code == 2 and "mutually exclusive" in rejected.output


def test_benchmark_cli_passes_bounded_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    import eng.benchmark

    arguments: dict[str, object] = {}

    def fixture(**kwargs: object) -> dict[str, object]:
        arguments.update(kwargs)
        return {"fixture": True}

    monkeypatch.setattr(eng.benchmark, "run_benchmark", fixture)
    runner = CliRunner()
    result = runner.invoke(
        app, ["benchmark", "--repetitions", "2", "--seed", "3", "--scenario", "small_bug"]
    )
    assert result.exit_code == 0 and json.loads(result.output) == {"fixture": True}
    assert arguments == {"repetitions": 2, "seed": 3, "scenarios": ["small_bug"]}
    assert runner.invoke(app, ["benchmark", "--repetitions", "11"]).exit_code == 2


def test_v3_migration_keeps_historical_model_unknown(repo: Path) -> None:
    root = repo / ".engineering/state"
    root.mkdir()
    connection = sqlite3.connect(root / "eng.sqlite3")
    for migration in MIGRATIONS[:3]:
        connection.executescript(migration)
    task = Task(
        project=repo,
        config=load_config(repo),
        spec=TaskSpec(description="Fix answer", acceptance=["pass"], model="present-default"),
        execution_id="old",
    )
    connection.execute("INSERT INTO projects VALUES (?,?)", (str(repo), "fixture"))
    connection.execute(
        "INSERT INTO tasks VALUES (?,?,?,?,0)",
        (task.id, str(repo), task.state.value, task.model_dump_json()),
    )
    connection.execute(
        "INSERT INTO executions(id,task_id,started_at) VALUES (?,?,?)",
        (task.execution_id, task.id, task.created_at),
    )
    connection.execute(
        "INSERT INTO invocations VALUES (?,?,?,?,?,?)",
        (
            "call",
            "old",
            "engineer",
            "fake",
            "success",
            ProviderResult(status="success", usage=Usage(input_tokens=8)).model_dump_json(),
        ),
    )
    connection.execute("PRAGMA user_version=3")
    connection.commit()
    connection.close()
    store = Store(repo)
    row = store.invocations(task.id)[0]
    assert row.model is None and row.result is not None and row.result.usage.input_tokens == 8
    store.close()


def test_role_mutation_retains_received_usage_and_duration(repo: Path, tmp_path: Path) -> None:
    class Mutating(FakeProvider):
        async def execute(
            self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
        ) -> ProviderResult:
            (request.workspace / "answer.txt").write_text("changed")
            return ProviderResult(
                status="success",
                duration_seconds=2.5,
                usage=Usage(input_tokens=123, cost_usd=0.2, cost_source="client_estimate"),
            )

    task = Task(
        project=repo,
        workspace=repo,
        config=load_config(repo),
        spec=TaskSpec(description="Inspect", acceptance=["pass"], provider="fake"),
    )
    request = ProviderRequest(
        task_id=task.id,
        execution_id="one",
        role=Role.REVIEWER,
        workspace=repo,
        prompt="Inspect",
        timeout_seconds=60,
    )
    result = asyncio.run(execute_role(Mutating(), request, task, tmp_path / "a", lambda: False))
    assert result.status == "error" and result.error_kind == "role_mutation"
    assert result.duration_seconds == 2.5 and result.usage.input_tokens == 123
    assert result.usage.cost_source == "client_estimate"

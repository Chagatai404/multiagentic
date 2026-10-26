"""Offline admission, recovery, and role guards with deterministic providers only."""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import pytest

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
from eng.core.plan import NodeStatus, PlanSpec, PlanStatus
from eng.providers.fake import FakeProvider
from eng.scheduling.runner import PlanRunner
from eng.storage.store import PlanBudgetStop, Store


class ReportedProvider(FakeProvider):
    async def execute(
        self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
    ) -> ProviderResult:
        result = await super().execute(request, artifact_dir, cancelled)
        if request.role == Role.ENGINEER:
            for name in ("a", "b"):
                if f"NODE:{name}" in request.prompt:
                    (request.workspace / "files" / f"{name}.txt").write_text(name.upper())
        result.usage = Usage(input_tokens=10, output_tokens=2, source="provider")
        return result


def spec(**extra: object) -> PlanSpec:
    return PlanSpec.model_validate(
        {
            "name": "budgets",
            "concurrency": 3,
            "provider": "fake",
            "nodes": [
                {
                    "id": n,
                    "description": f"NODE:{n} Create file",
                    "acceptance": ["checks pass"],
                    "owns": [f"files/{n}.txt"],
                }
                for n in ("a", "b")
            ],
            **extra,
        }
    )


def test_finite_limit_serializes_and_stops_before_next_node(plan_repo: Path) -> None:
    provider = ReportedProvider()
    runner = PlanRunner(plan_repo, lambda name, config: provider, poll_seconds=0.01)
    store = Store(plan_repo)
    plan = runner.create(store, spec(limits={"reported_input_tokens": 10}))
    done = runner.run(plan.id)
    assert done.status == PlanStatus.PAUSED and "reached" in done.message
    assert done.node("a").status == NodeStatus.INTEGRATED
    assert done.node("b").task_id is None
    assert store.plan_reservations(plan.id)[0]["status"] == "settled"
    assert runner.run(plan.id, resume=True, clear_limits=True).status == PlanStatus.READY
    store.close()


def test_effective_budget_is_saved_before_project_changes(plan_repo: Path) -> None:
    from eng.projects.config import load_config

    config = load_config(plan_repo)
    config.budgets.model_calls = 7
    provider = ReportedProvider()
    runner = PlanRunner(plan_repo, lambda name, config: provider)
    store = Store(plan_repo)
    raw = spec(node_budgets={"context_chars": 2000})
    raw.nodes[0].budgets = {"model_calls": 2}  # type: ignore[assignment]
    plan = runner.create(store, raw, config)
    assert plan.node("a").effective_budgets.model_calls == 2  # type: ignore[union-attr]
    assert plan.node("b").effective_budgets.model_calls == 7  # type: ignore[union-attr]
    changed = load_config(plan_repo)
    changed.budgets.model_calls = 1
    task = runner._new_task(store.load_plan(plan.id), plan.node("b"), changed, False)
    assert task.spec.budgets.model_calls == 7 and task.spec.budgets.context_chars == 2000
    store.close()


@pytest.mark.parametrize(
    "limit", ["reported_input_tokens", "reported_output_tokens", "reported_cost_usd"]
)
def test_unknown_coverage_stops_independent_parallel_launches(plan_repo: Path, limit: str) -> None:
    provider = FakeProvider({"files/a.txt": "A"})
    runner = PlanRunner(plan_repo, lambda name, config: provider, poll_seconds=0.01)
    store = Store(plan_repo)
    plan = runner.create(store, spec(limits={limit: 100}))
    done = runner.run(plan.id)
    assert done.status == PlanStatus.PAUSED and "unknown" in done.message
    assert done.node("a").status == NodeStatus.INTEGRATED
    assert done.node("b").task_id is None
    assert store.plan_reservations(plan.id)[0]["status"] == "uncertain"
    assert runner.run(plan.id, resume=True).node("b").task_id is None
    store.close()


def test_plan_threshold_applies_between_roles_and_direct_task_resume(plan_repo: Path) -> None:
    provider = ReportedProvider()
    runner = PlanRunner(plan_repo, lambda name, config: provider, poll_seconds=0.01)
    store = Store(plan_repo)
    raw = spec(node_budgets={"model_calls": 5}, limits={"reported_input_tokens": 10})
    raw.nodes[0].description = "NODE:a Refactor complex architecture"
    plan = runner.create(store, raw)
    done = runner.run(plan.id)
    task_id = done.node("a").task_id
    assert task_id is not None
    task = store.load(task_id)
    assert task.state == State.PAUSED and task.planning_completed
    assert len(store.invocations(task_id)) == 1
    resumed = asyncio.run(Engine(store, provider).execute(task_id, resume=True))
    assert resumed.state == State.PAUSED and "Plan:" in resumed.message
    assert len(store.invocations(task_id)) == 1
    store.close()


class ReviewRepairProvider(FakeProvider):
    def __init__(self, *, reported: bool = True) -> None:
        super().__init__({"answer.txt": "42"})
        self.roles: list[Role] = []
        self.reported = reported

    async def execute(
        self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
    ) -> ProviderResult:
        self.roles.append(request.role)
        result = await super().execute(request, artifact_dir, cancelled)
        if request.role == Role.REVIEWER:
            result.summary = json.dumps(
                {
                    "summary": "Apply requested adjustment",
                    "verdict": "changes_requested",
                    "findings": ["Adjust answer presentation"],
                }
            )
        if self.reported:
            result.usage = Usage(input_tokens=10, output_tokens=2, source="provider")
        return result


@pytest.mark.parametrize(
    "allocation,reported,message",
    [
        ({"model_calls": 1}, True, "CLI invocation allocation exhausted"),
        ({"reported_input_tokens": 10}, True, "stop threshold reached"),
        ({"reported_output_tokens": 5}, False, "coverage unknown"),
    ],
)
def test_role_limits_pause_repeated_review_without_waiving_it(
    repo: Path,
    allocation: dict[str, int],
    reported: bool,
    message: str,
) -> None:
    from eng.projects.config import load_config

    store = Store(repo)
    task = Task(
        project=repo,
        config=load_config(repo),
        spec=TaskSpec(
            description="Refactor complex answer architecture",
            acceptance=["pass"],
            provider="fake",
            budgets=Budgets(model_calls=10, role_limits={Role.REVIEWER: allocation}),
        ),
    )
    store.create(task)
    provider = ReviewRepairProvider(reported=reported)
    done = asyncio.run(Engine(store, provider).execute(task.id))
    assert done.state == State.PAUSED and message in done.message
    assert provider.roles == [Role.PLANNER, Role.ENGINEER, Role.REVIEWER, Role.DEBUGGER]
    assert not done.review_passed and done.next_role == Role.REVIEWER
    assert done.provider_calls == 4
    store.close()


def test_role_allocation_cannot_increase_overall_cli_call_limit(repo: Path) -> None:
    from eng.projects.config import load_config

    store = Store(repo)
    task = Task(
        project=repo,
        config=load_config(repo),
        spec=TaskSpec(
            description="Create answer",
            acceptance=["pass"],
            provider="fake",
            classification_overrides=ClassificationOverrides(complexity=Complexity.COMPLEX),
            budgets=Budgets(model_calls=1, role_limits={Role.ENGINEER: {"model_calls": 10}}),
        ),
    )
    store.create(task)
    provider = ReviewRepairProvider()
    done = asyncio.run(Engine(store, provider).execute(task.id))
    assert done.state == State.PAUSED and "Model-call budget exhausted" in done.message
    assert provider.roles == [Role.PLANNER] and done.provider_calls == 1
    store.close()


def test_transactional_rejection_restores_pre_call_checkpoint_and_count(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eng.projects.config import load_config

    store = Store(repo)
    task = Task(
        project=repo,
        config=load_config(repo),
        spec=TaskSpec(description="Create answer", acceptance=["pass"], provider="fake"),
    )
    store.create(task)

    def reject(task: Task) -> None:
        raise PlanBudgetStop("Reported input_tokens stop threshold reached")

    monkeypatch.setattr(store, "begin_invocation", reject)
    provider = ReviewRepairProvider()
    done = asyncio.run(Engine(store, provider).execute(task.id))
    assert done.state == State.PAUSED and "Plan:" in done.message
    assert done.checkpoint == "prepared" and done.provider_calls == 0
    assert done.pending_invocation_id is None and not store.invocations(task.id)
    assert not provider.roles
    store.close()


def test_known_timeout_usage_keeps_unknown_outcome_reservation(plan_repo: Path) -> None:
    class TimeoutProvider(FakeProvider):
        async def execute(
            self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
        ) -> ProviderResult:
            return ProviderResult(
                status="timeout",
                error_kind="timeout",
                usage=Usage(input_tokens=1, output_tokens=1, source="provider"),
            )

    provider = TimeoutProvider()
    runner = PlanRunner(plan_repo, lambda name, config: provider, poll_seconds=0.01)
    store = Store(plan_repo)
    plan = runner.create(store, spec(limits={"reported_input_tokens": 100}))
    done = runner.run(plan.id, keep_going=True)
    assert done.status == PlanStatus.PAUSED
    assert done.node("b").task_id is None and "reservation" in done.message
    assert store.plan_reservations(plan.id)[0]["status"] == "uncertain"
    store.close()


@pytest.mark.parametrize("integrated", [False, True])
def test_crash_after_finished_node_before_lease_settlement_recovers(
    plan_repo: Path,
    integrated: bool,
) -> None:
    from eng.projects.config import load_config
    from eng.scheduling.integration import integrate_node

    provider = ReportedProvider()
    runner = PlanRunner(plan_repo, lambda name, config: provider, poll_seconds=0.01)
    store = Store(plan_repo)
    plan = runner.create(store, spec(limits={"reported_input_tokens": 100}))
    node = plan.node("a")
    task = runner._new_task(plan, node, load_config(plan_repo), False)
    node.base_commit = plan.head_commit
    assert store.claim_plan_launch(plan, node, task) is None
    done = asyncio.run(Engine(store, provider).execute(task.id))
    assert done.state == State.COMPLETED
    node.status = NodeStatus.VERIFIED
    store.save_plan(plan)  # precise collect crash window: finished, lease still reserved
    if integrated:
        assert integrate_node(store, plan, node, lambda: False)
    assert store.plan_reservations(plan.id)[0]["status"] == "reserved"
    recovered = runner.run(plan.id, resume=True)
    assert recovered.status == PlanStatus.READY, recovered.message
    assert all(n.status == NodeStatus.INTEGRATED for n in recovered.nodes)
    assert {row["status"] for row in store.plan_reservations(plan.id)} == {"settled"}
    store.close()

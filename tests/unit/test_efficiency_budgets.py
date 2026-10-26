"""Budget inheritance and admission are checked before changing scheduler behavior."""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import ValidationError

from eng.core.models import Budgets, ProjectConfig, Role, Task, TaskSpec, identity
from eng.core.plan import (
    BudgetOverrides,
    PlanNode,
    PlanNodeSpec,
    PlanRecord,
    PlanSpec,
    resolve_budgets,
)
from eng.execution.workspace import task_lock
from eng.providers.fake import FakeProvider
from eng.scheduling.runner import PlanRunner
from eng.storage.store import PlanBudgetStop, Store


def plan_record(root: Path, **extra: object) -> PlanRecord:
    spec = PlanSpec.model_validate(
        {
            "name": "budget",
            "nodes": [
                {"id": name, "description": "Create file", "acceptance": ["pass"], "owns": [name]}
                for name in ("a", "b")
            ],
            **extra,
        }
    )
    return PlanRecord(
        project=root,
        spec=spec,
        nodes=[PlanNode(spec=n) for n in spec.nodes],
        base_commit="a" * 40,
        branch="eng/plan/test",
        workspace=root / "integration",
        head_commit="a" * 40,
    )


def task_for(root: Path) -> Task:
    return Task(
        project=root,
        config=ProjectConfig(),
        spec=TaskSpec(description="Create file", acceptance=["pass"], provider="fake"),
    )


def test_partial_overrides_preserve_project_values_and_merge_role_fields() -> None:
    base = Budgets(
        model_calls=7,
        context_chars=9000,
        reported_input_tokens=700,
        role_limits={Role.REVIEWER: {"model_calls": 2, "reported_output_tokens": 30}},
    )
    defaults = BudgetOverrides(model_calls=5, role_limits={Role.REVIEWER: {"model_calls": 1}})
    node = BudgetOverrides(context_chars=800, reported_input_tokens=50)
    result = resolve_budgets(base, defaults, node)
    assert result.model_calls == 5 and result.context_chars == 800
    assert result.reported_input_tokens == 50
    assert result.role_limits[Role.REVIEWER].model_calls == 1
    assert result.role_limits[Role.REVIEWER].reported_output_tokens == 30
    assert base.model_calls == 7


@pytest.mark.parametrize(
    "values",
    [
        {"model_calls": 0},
        {"context_chars": 255},
        {"provider_seconds": float("nan")},
        {"reported_input_tokens": -1},
        {"reported_cost_usd": float("inf")},
        {"typo": 1},
        {"role_limits": {"verifier": {"model_calls": 1}}},
    ],
)
def test_invalid_overrides_rejected(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BudgetOverrides.model_validate(values)


def test_default_concurrency_one_and_explicit_legacy_three_round_trip(tmp_path: Path) -> None:
    plan = plan_record(tmp_path)
    assert plan.spec.concurrency == 1
    plan.spec.concurrency = 3
    assert PlanRecord.model_validate_json(plan.model_dump_json()).spec.concurrency == 3
    node = PlanNodeSpec.model_validate(
        {
            "id": "css",
            "description": "Fix color",
            "acceptance": ["pass"],
            "owns": ["a.css"],
            "budgets": {"model_calls": 2},
            "max_repairs": 0,
        }
    )
    assert node.budgets and node.budgets.model_calls == 2 and node.max_repairs == 0


def test_transactional_admission_serializes_finite_limits_across_stores(tmp_path: Path) -> None:
    first = Store(tmp_path)
    plan = plan_record(tmp_path, limits={"reported_input_tokens": 100}, concurrency=3)
    first.create_plan(plan)
    barrier = Barrier(2)

    def claim(name: str) -> bool:
        store = Store(tmp_path)
        try:
            local = store.load_plan(plan.id)
            barrier.wait(timeout=10)
            return store.claim_plan_launch(local, local.node(name), task_for(tmp_path)) is None
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ("a", "b")))
    assert sum(results) == 1
    persisted = first.load_plan(plan.id)
    assert sum(n.task_id is not None for n in persisted.nodes) == 1
    assert len(first.list_tasks()) == 1  # rejected admission never creates an orphan
    assert first.plan_reservations(plan.id)[0]["status"] == "reserved"
    first.close()


def test_reservation_survives_restart_and_same_node_can_recover_before_call(tmp_path: Path) -> None:
    store = Store(tmp_path)
    plan = plan_record(tmp_path, limits={"reported_input_tokens": 100})
    store.create_plan(plan)
    task = task_for(tmp_path)
    assert store.claim_plan_launch(plan, plan.node("a"), task) is None
    store.close()
    store = Store(tmp_path)
    plan = store.load_plan(plan.id)
    assert "reservation" in (
        store.claim_plan_launch(plan, plan.node("b"), task_for(tmp_path)) or ""
    )
    assert store.claim_plan_launch(plan, plan.node("a"), store.load(task.id)) is None
    store.settle_plan_launch(plan.id, "a")
    assert store.claim_plan_launch(plan, plan.node("b"), task_for(tmp_path)) is None
    store.close()


def pending_call(store: Store, task: Task) -> Task:
    task.execution_id = identity()
    store.start_execution(task)
    task.pending_role = Role.ENGINEER
    task.pending_invocation_id = identity()
    task.provider_calls += 1
    task.checkpoint = "provider_started"
    return task


def test_unknown_provider_outcome_keeps_reservation_and_history_after_restart(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path)
    plan = plan_record(tmp_path, limits={"reported_output_tokens": 100})
    store.create_plan(plan)
    task = task_for(tmp_path)
    assert store.claim_plan_launch(plan, plan.node("a"), task) is None
    store.begin_invocation(pending_call(store, task))
    store.settle_plan_launch(plan.id, "a")
    assert store.plan_reservations(plan.id)[0]["status"] == "uncertain"
    store.close()
    store = Store(tmp_path)
    plan = store.load_plan(plan.id)
    assert "reservation" in (
        store.claim_plan_launch(plan, plan.node("b"), task_for(tmp_path)) or ""
    )
    assert "unknown" in (store.plan_budget_stop_reason(task.id) or "")
    plan.spec.limits.reported_output_tokens = None
    store.save_plan(plan)
    store.clear_plan_reservations(plan.id)
    assert store.claim_plan_launch(plan, plan.node("b"), task_for(tmp_path)) is None
    assert (
        store.invocations(task.id)[0].status == "started"
    )  # explicit clearing never invents usage
    store.close()


def test_direct_continuations_claim_lease_in_same_transaction_as_provider_reservation(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path)
    plan = plan_record(tmp_path)
    store.create_plan(plan)
    tasks = [task_for(tmp_path), task_for(tmp_path)]
    for name, task in zip(("a", "b"), tasks, strict=True):
        assert store.claim_plan_launch(plan, plan.node(name), task) is None
        store.settle_plan_launch(plan.id, name)
        pending_call(store, task)
    plan.spec.limits.reported_input_tokens = 100
    store.save_plan(plan)
    barrier = Barrier(2)

    def begin(task: Task) -> bool:
        worker = Store(tmp_path)
        try:
            barrier.wait(timeout=10)
            try:
                worker.begin_invocation(task)
                return True
            except PlanBudgetStop:
                return False
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sum(executor.map(begin, tasks)) == 1
    assert store.connection.execute("SELECT COUNT(*) FROM invocations").fetchone()[0] == 1
    assert sum(row["status"] == "reserved" for row in store.plan_reservations(plan.id)) == 1
    store.close()


def test_parallel_forward_migration_backfills_legacy_membership(tmp_path: Path) -> None:
    store = Store(tmp_path)
    plan = plan_record(tmp_path, concurrency=3, limits={"reported_input_tokens": 10})
    store.create_plan(plan)
    task = task_for(tmp_path)
    assert store.claim_plan_launch(plan, plan.node("a"), task) is None
    with store.connection:
        store.connection.execute("DROP TABLE plan_launches")
        store.connection.execute("PRAGMA user_version=5")
    store.close()
    barrier = Barrier(2)

    def open_store(_: int) -> tuple[int, str]:
        barrier.wait(timeout=10)
        worker = Store(tmp_path)
        try:
            return worker.load_plan(plan.id).spec.concurrency, worker.plan_reservations(plan.id)[0][
                "task_id"
            ]
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(open_store, (1, 2))) == [(3, task.id), (3, task.id)]


def test_legacy_full_budget_replacement_retains_null_reported_thresholds(tmp_path: Path) -> None:
    config = ProjectConfig(budgets=Budgets(model_calls=8, reported_input_tokens=100))
    plan = plan_record(tmp_path, node_budgets=Budgets(model_calls=3).model_dump())
    runner = PlanRunner(tmp_path, lambda name, config: FakeProvider())
    legacy = runner._new_task(plan, plan.node("a"), config, False)
    assert legacy.spec.budgets.model_calls == 3
    assert legacy.spec.budgets.reported_input_tokens is None
    current = plan_record(tmp_path, node_budgets={"model_calls": 3})
    current.budget_schema_version = 2
    additive = runner._new_task(current, current.node("a"), config, False)
    assert additive.spec.budgets.reported_input_tokens == 100


def test_repair_zero_overrides_and_effective_budgets_do_not_alias_config(tmp_path: Path) -> None:
    config = ProjectConfig(budgets=Budgets(model_calls=8))
    config.workflow.max_repairs = 2
    plan = plan_record(tmp_path, node_max_repairs=1)
    plan.node("a").spec.max_repairs = 0
    runner = PlanRunner(tmp_path, lambda name, config: FakeProvider())
    task = runner._new_task(plan, plan.node("a"), config, False)
    assert task.config.workflow.max_repairs == 0 and config.workflow.max_repairs == 2
    config.budgets.model_calls = 1
    task_again = runner._new_task(plan, plan.node("a"), config, False)
    assert task_again.spec.budgets.model_calls == 8
    task.spec.budgets.model_calls = 2
    assert plan.node("a").effective_budgets.model_calls == 8  # type: ignore[union-attr]


def test_process_death_preserves_committed_launch_reservation(tmp_path: Path) -> None:
    store = Store(tmp_path)
    plan = plan_record(tmp_path, limits={"reported_input_tokens": 100})
    store.create_plan(plan)
    script = """
import os,sys
from pathlib import Path
from eng.core.models import ProjectConfig,Task,TaskSpec
from eng.storage.store import Store
root=Path(sys.argv[1]); store=Store(root); plan=store.load_plan(sys.argv[2])
spec=TaskSpec(description='Create file',acceptance=['pass'])
task=Task(project=root,config=ProjectConfig(),spec=spec)
assert store.claim_plan_launch(plan,plan.node('a'),task) is None
os._exit(0)
"""
    subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), plan.id],
        check=True,
        capture_output=True,
        timeout=20,
    )
    recovered = store.load_plan(plan.id)
    assert recovered.node("a").task_id is not None
    assert "reservation" in (
        store.claim_plan_launch(recovered, recovered.node("b"), task_for(tmp_path)) or ""
    )
    assert len(store.list_tasks()) == 1
    store.close()


def test_settlement_does_not_release_an_active_direct_continuation(tmp_path: Path) -> None:
    store = Store(tmp_path)
    plan = plan_record(tmp_path, limits={"reported_input_tokens": 100})
    store.create_plan(plan)
    task = task_for(tmp_path)
    assert store.claim_plan_launch(plan, plan.node("a"), task) is None
    with task_lock(tmp_path, task.id):
        store.settle_plan_launch(plan.id, "a")
        assert store.plan_reservations(plan.id)[0]["status"] == "reserved"
    store.settle_plan_launch(plan.id, "a")
    assert store.plan_reservations(plan.id)[0]["status"] == "settled"
    store.close()

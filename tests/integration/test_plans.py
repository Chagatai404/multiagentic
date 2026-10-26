import asyncio
import re
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from eng.core.models import Check, ProjectConfig, ProviderRequest, ProviderResult, Risk, Role, State
from eng.core.plan import NodeStatus, PlanRecord, PlanSpec, PlanStatus
from eng.execution.integrate import commit_tree, head, reset_integration
from eng.execution.workspace import git
from eng.providers.fake import FakeProvider
from eng.scheduling.integration import integrate_node, promote, promotion_report
from eng.scheduling.runner import PlanRunner, SlotPool
from eng.storage.store import Store


class Tracker:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.current = 0
        self.peak = 0
        self.bases: dict[str, bool] = {}


class NodeProvider(FakeProvider):
    """Applies per-node edits keyed by a NODE:<id> marker in the task description."""

    def __init__(
        self, edits: dict[str, dict[str, str]], tracker: Tracker, delay: float = 0.0
    ) -> None:
        super().__init__()
        self.edits = edits
        self.tracker = tracker
        self.delay = delay

    async def execute(
        self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
    ) -> ProviderResult:
        if request.role in {Role.PLANNER, Role.REVIEWER}:
            return await super().execute(request, artifact_dir, cancelled)
        match = re.search(r"NODE:(\w+)", request.prompt)
        assert match, "prompt must name its node"
        node = match.group(1)
        with self.tracker.lock:
            self.tracker.current += 1
            self.tracker.peak = max(self.tracker.peak, self.tracker.current)
        try:
            await asyncio.sleep(self.delay)
            # A dependent must start from the integrated work of its dependencies.
            self.tracker.bases[node] = (request.workspace / "files" / "a.txt").exists()
            for relative, content in self.edits.get(node, {}).items():
                target = request.workspace / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        finally:
            with self.tracker.lock:
                self.tracker.current -= 1
        return ProviderResult(status="success", summary=f"edited {node}")


def spec_of(*nodes: dict[str, Any], **extra: Any) -> PlanSpec:
    return PlanSpec.model_validate(
        {"name": "plan", "nodes": list(nodes), "provider": "fake", **extra}
    )


def node(
    node_id: str, owns: list[str], depends_on: list[str] | None = None, **extra: Any
) -> dict[str, Any]:
    return {
        "id": node_id,
        "description": f"NODE:{node_id} create the file",
        "acceptance": ["checks pass"],
        "owns": owns,
        "depends_on": depends_on or [],
        **extra,
    }


def file_edit(name: str) -> dict[str, str]:
    return {f"files/{name}.txt": name.upper()}


def make_runner(repo: Path, provider: FakeProvider) -> PlanRunner:
    return PlanRunner(repo, lambda name, config: provider, poll_seconds=0.02)


def run_plan(
    repo: Path, spec: PlanSpec, provider: FakeProvider, **options: Any
) -> tuple[PlanRunner, Store, PlanRecord]:
    runner = make_runner(repo, provider)
    store = Store(repo)
    plan = runner.create(store, spec)
    return runner, store, runner.run(plan.id, **options)


def node_concurrency(store: Store, plan_id: str) -> int:
    """Peak number of nodes between node_started and node_finished, from recorded events.

    Unlike overlap inside the provider call (a short slice of a node's life that depends
    on machine speed), this measures how many nodes the coordinator really had in flight.
    """
    running = peak = 0
    for event in store.plan_events(plan_id):
        if event["kind"] == "node_started":
            running += 1
            peak = max(peak, running)
        elif event["kind"] == "node_finished":
            running -= 1
    return peak


def main_is_clean(repo: Path) -> bool:
    return git(repo, "status", "--porcelain", "--untracked-files=normal") == ""


def test_independent_nodes_run_concurrently_and_integrate(plan_repo: Path) -> None:
    tracker = Tracker()
    edits = {name: file_edit(name) for name in ("a", "b", "c", "d")}
    provider = NodeProvider(edits, tracker, delay=0.5)
    base = head(plan_repo)
    spec = spec_of(
        node("a", ["files/a.txt"]),
        node("b", ["files/b.txt"]),
        node("c", ["files/c.txt"]),
        node("d", ["files/d.txt"], ["a"]),
        concurrency=3,
    )
    _, store, plan = run_plan(plan_repo, spec, provider)
    assert plan.status == PlanStatus.READY, plan.message
    assert [n.status for n in plan.nodes] == [NodeStatus.INTEGRATED] * 4
    assert 2 <= node_concurrency(store, plan.id) <= 3
    assert tracker.peak <= 3
    assert tracker.bases["d"] is True  # dependent started from the integrated head
    assert tracker.bases["a"] is False
    assert plan.final_verified and plan.head_commit != base
    tree = git(plan_repo, "ls-tree", "-r", "--name-only", plan.branch).splitlines()
    assert {"files/a.txt", "files/b.txt", "files/c.txt", "files/d.txt"} <= set(tree)
    # The user's checkout and branch are untouched until an explicit promotion.
    assert head(plan_repo) == base and main_is_clean(plan_repo)
    tasks = [store.load(n.task_id or "") for n in plan.nodes]
    assert all(t.state == State.COMPLETED and t.spec.owned_paths for t in tasks)
    assert len({t.workspace for t in tasks}) == 4  # independent worktrees
    store.close()


def test_concurrency_one_serializes_nodes(plan_repo: Path) -> None:
    tracker = Tracker()
    provider = NodeProvider({n: file_edit(n) for n in ("a", "b", "c")}, tracker, delay=0.1)
    spec = spec_of(
        node("a", ["files/a.txt"]),
        node("b", ["files/b.txt"]),
        node("c", ["files/c.txt"]),
        concurrency=1,
    )
    _, store, plan = run_plan(plan_repo, spec, provider)
    assert plan.status == PlanStatus.READY and tracker.peak == 1
    assert node_concurrency(store, plan.id) == 1
    store.close()


def test_ownership_violation_fails_node_and_skips_dependents(plan_repo: Path) -> None:
    edits = {"a": {"files/a.txt": "A", "files/zzz.txt": "ZZZ"}, "b": file_edit("b")}
    spec = spec_of(node("a", ["files/a.txt"]), node("b", ["files/b.txt"], ["a"]))
    _, store, plan = run_plan(plan_repo, spec, NodeProvider(edits, Tracker()))
    assert plan.status == PlanStatus.FAILED
    assert plan.node("a").status == NodeStatus.FAILED
    assert "outside ownership" in plan.node("a").message
    assert plan.node("b").status == NodeStatus.SKIPPED and plan.node("b").task_id is None
    assert head(plan.workspace) == plan.base_commit  # nothing integrated
    store.close()


def test_integrated_tree_failure_rolls_back(plan_repo: Path) -> None:
    edits = {"xa": file_edit("xa"), "xb": file_edit("xb")}
    spec = spec_of(node("xa", ["files/xa.txt"]), node("xb", ["files/xb.txt"]), concurrency=2)
    provider = NodeProvider(edits, Tracker(), delay=0.3)
    _, store, plan = run_plan(plan_repo, spec, provider)
    # Both start from the same base and each passes alone; only the combination fails.
    statuses = sorted(n.status.value for n in plan.nodes)
    assert statuses == ["BLOCKED", "INTEGRATED"]
    integrated = next(n for n in plan.nodes if n.status == NodeStatus.INTEGRATED)
    refused = next(n for n in plan.nodes if n.status == NodeStatus.BLOCKED)
    assert "failed verification" in refused.message
    assert plan.status == PlanStatus.BLOCKED
    assert plan.head_commit == integrated.integrated_commit == head(plan.workspace)
    assert git(plan.workspace, "status", "--porcelain") == ""
    assert not (plan.workspace / "files" / f"{refused.spec.id}.txt").exists()
    assert refused.task_id and store.load(refused.task_id).state == State.COMPLETED
    store.close()


def test_merge_conflict_blocks_without_moving_head(plan_repo: Path) -> None:
    edits = {"a": {"files/a.txt": "A"}}
    runner = make_runner(plan_repo, NodeProvider(edits, Tracker()))
    store = Store(plan_repo)
    plan = runner.create(store, spec_of(node("a", ["files/a.txt"])))
    # Run the node's task but integrate by hand after the integration head moves.
    from eng.core.engine import Engine
    from eng.core.models import Task, TaskSpec
    from eng.projects.config import load_config

    task = Task(
        project=plan_repo,
        config=load_config(plan_repo),
        spec=TaskSpec(
            description="NODE:a",
            acceptance=["x"],
            provider="fake",
            base_commit=plan.head_commit,
            owned_paths=["files/a.txt"],
        ),
    )
    store.create(task)
    asyncio.run(Engine(store, runner.provider_factory("fake", task.config)).execute(task.id))
    assert store.load(task.id).state == State.COMPLETED
    # A concurrent writer adds the same file with different content.
    (plan.workspace / "files").mkdir(exist_ok=True)
    (plan.workspace / "files" / "a.txt").write_text("OTHER", encoding="utf-8")
    git(plan.workspace, "add", "-A")
    tree = git(plan.workspace, "write-tree")
    moved = commit_tree(plan.workspace, tree, plan.head_commit, "other writer")
    reset_integration(plan.workspace, moved)
    plan.head_commit = moved
    plan_node = plan.node("a")
    plan_node.task_id, plan_node.status = task.id, NodeStatus.VERIFIED
    assert integrate_node(store, plan, plan_node, lambda: False) is False
    assert plan_node.status == NodeStatus.BLOCKED and "Merge conflict" in plan_node.message
    assert plan.head_commit == moved == head(plan.workspace)
    store.close()


def test_promotion_requires_approval_and_is_fast_forward_only(plan_repo: Path) -> None:
    provider = NodeProvider({"a": file_edit("a")}, Tracker())
    _, store, plan = run_plan(plan_repo, spec_of(node("a", ["files/a.txt"])), provider)
    before = head(plan_repo)
    dry = promote(store, plan, approved=False)
    assert dry["promotable"] is True and dry["promoted"] is False and head(plan_repo) == before
    assert store.load_plan(plan.id).status == PlanStatus.READY
    done = promote(store, plan, approved=True)
    assert done["promoted"] is True
    assert head(plan_repo) == plan.head_commit and (plan_repo / "files" / "a.txt").is_file()
    assert store.load_plan(plan.id).status == PlanStatus.PROMOTED
    assert promote(store, plan, approved=True)["promoted"] is False  # not twice
    assert not subprocess.run(
        ["git", "-C", str(plan_repo), "remote"], capture_output=True, text=True
    ).stdout  # eng never configures or uses a remote
    store.close()


def test_promotion_refuses_unsafe_checkouts(plan_repo: Path) -> None:
    provider = NodeProvider({"a": file_edit("a")}, Tracker())
    _, store, plan = run_plan(plan_repo, spec_of(node("a", ["files/a.txt"])), provider)
    (plan_repo / "scratch.txt").write_text("dirty", encoding="utf-8")
    report = promote(store, plan, approved=True)
    assert not report["promotable"] and any("uncommitted" in p for p in report["problems"])
    (plan_repo / "scratch.txt").unlink()
    (plan_repo / "other.txt").write_text("diverge", encoding="utf-8")
    git(plan_repo, "add", "-A")
    git(plan_repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "diverge")
    report = promotion_report(plan)
    assert any("fast-forward" in p for p in report["problems"])
    assert promote(store, plan, approved=True)["promoted"] is False
    git(plan_repo, "checkout", "--detach", "-q")
    assert any("detached" in p for p in promotion_report(plan)["problems"])
    store.close()


def test_promotion_detects_tampered_plan_branch(plan_repo: Path) -> None:
    provider = NodeProvider({"a": file_edit("a")}, Tracker())
    _, store, plan = run_plan(plan_repo, spec_of(node("a", ["files/a.txt"])), provider)
    (plan.workspace / "files" / "evil.txt").write_text("EVIL", encoding="utf-8")
    git(plan.workspace, "add", "-A")
    git(plan.workspace, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "tamper")
    report = promotion_report(plan)
    assert any("moved" in p for p in report["problems"])
    assert promote(store, plan, approved=True)["promoted"] is False
    store.close()


def test_high_risk_node_pauses_until_explicitly_approved(plan_repo: Path) -> None:
    provider = NodeProvider({"a": file_edit("a")}, Tracker())
    spec = spec_of(
        node("a", ["files/a.txt"], risk=Risk.HIGH.value), node_budgets={"model_calls": 4}
    )
    runner, store, plan = run_plan(plan_repo, spec, provider)
    assert plan.status == PlanStatus.PAUSED and plan.node("a").status == NodeStatus.PAUSED
    assert "approve-high-risk" in plan.node("a").message
    runner.approve_node(store, plan.id, "a")
    plan = runner.run(plan.id, resume=True)
    assert plan.status == PlanStatus.READY
    events = [e["kind"] for e in store.events(plan.node("a").task_id or "")]
    assert "human_approved" in events
    store.close()


def test_run_level_approval_applies_to_every_node(plan_repo: Path) -> None:
    provider = NodeProvider({"a": file_edit("a")}, Tracker())
    spec = spec_of(
        node("a", ["files/a.txt"], risk=Risk.HIGH.value), node_budgets={"model_calls": 4}
    )
    _, store, plan = run_plan(plan_repo, spec, provider, approve_high_risk=True)
    assert plan.status == PlanStatus.READY
    store.close()


def test_plan_limit_with_unknown_usage_stops_new_launches(plan_repo: Path) -> None:
    edits = {name: file_edit(name) for name in ("a", "b")}
    spec = spec_of(
        node("a", ["files/a.txt"]),
        node("b", ["files/b.txt"], ["a"]),
        limits={"reported_input_tokens": 1000},
    )
    _, store, plan = run_plan(plan_repo, spec, NodeProvider(edits, Tracker()))
    assert plan.node("a").status == NodeStatus.INTEGRATED
    assert plan.node("b").status == NodeStatus.PENDING and plan.node("b").task_id is None
    assert "coverage unknown" in plan.message and plan.status == PlanStatus.PAUSED
    # Unknown coverage never clears itself; only an explicit human action lifts the limit.
    runner = make_runner(plan_repo, NodeProvider(edits, Tracker()))
    assert runner.run(plan.id, resume=True).status == PlanStatus.PAUSED
    done = runner.run(plan.id, resume=True, clear_limits=True)
    assert done.status == PlanStatus.READY and not done.spec.limits.reported_input_tokens
    assert "limits_cleared" in [e["kind"] for e in store.plan_events(plan.id)]
    store.close()


def test_resume_integrates_a_completed_node_after_a_coordinator_crash(plan_repo: Path) -> None:
    provider = NodeProvider({"a": file_edit("a"), "b": file_edit("b")}, Tracker())
    spec = spec_of(node("a", ["files/a.txt"]), node("b", ["files/b.txt"], ["a"]))
    runner, store, plan = run_plan(plan_repo, spec, provider, keep_going=True)
    assert plan.status == PlanStatus.READY
    # Simulate a crash after the engine finished but before integration was recorded.
    fresh = runner.create(store, spec)
    complete = runner.run(fresh.id)
    assert complete.status == PlanStatus.READY
    crashed = store.load_plan(complete.id)
    crashed.status = PlanStatus.RUNNING
    crashed.node("b").status = NodeStatus.RUNNING  # interrupted: task is COMPLETED
    store.save_plan(crashed)
    again = runner.run(crashed.id)
    assert again.node("b").status == NodeStatus.INTEGRATED and again.status == PlanStatus.READY
    store.close()


def test_reconcile_restores_unrecorded_integration_commit(plan_repo: Path) -> None:
    provider = NodeProvider({"a": file_edit("a")}, Tracker())
    runner, store, plan = run_plan(plan_repo, spec_of(node("a", ["files/a.txt"])), provider)
    recorded = plan.head_commit
    (plan.workspace / "files" / "ghost.txt").write_text("GHOST", encoding="utf-8")
    git(plan.workspace, "add", "-A")
    git(plan.workspace, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "unrecorded")
    assert head(plan.workspace) != recorded
    runner.run(plan.id)
    assert head(plan.workspace) == recorded
    assert "integration_reconciled" in [e["kind"] for e in store.plan_events(plan.id)]
    store.close()


def test_cancel_idle_plan_marks_nodes_cancelled(plan_repo: Path) -> None:
    runner = make_runner(plan_repo, NodeProvider({}, Tracker()))
    store = Store(plan_repo)
    plan = runner.create(store, spec_of(node("a", ["files/a.txt"])))
    cancelled = runner.cancel(store, plan.id)
    assert cancelled.status == PlanStatus.CANCELLED
    assert cancelled.node("a").status == NodeStatus.CANCELLED
    with pytest.raises(ValueError, match="cancelled"):
        runner.run(plan.id)
    store.close()


def test_cancel_during_run_stops_new_nodes(plan_repo: Path) -> None:
    tracker = Tracker()
    provider = NodeProvider({"a": file_edit("a"), "b": file_edit("b")}, tracker, delay=1.0)
    runner = make_runner(plan_repo, provider)
    store = Store(plan_repo)
    plan = runner.create(
        store, spec_of(node("a", ["files/a.txt"]), node("b", ["files/b.txt"], ["a"]))
    )
    timer = threading.Timer(0.5, lambda: Store(plan_repo).cancel_plan(plan.id))
    timer.start()
    result = runner.run(plan.id)
    timer.join()
    assert result.status == PlanStatus.CANCELLED
    assert result.node("b").task_id is None
    store.close()


def test_slot_pool_caps_at_three(tmp_path: Path) -> None:
    pool = SlotPool(tmp_path, size=10)
    handles = [pool.acquire() for _ in range(3)]
    assert all(h is not None for h in handles) and pool.acquire() is None
    pool.release(handles[0])  # type: ignore[arg-type]
    again = pool.acquire()
    assert again is not None
    for handle in [*handles[1:], again]:
        pool.release(handle)  # type: ignore[arg-type]


def test_runner_rejects_unknown_provider_before_any_effect(plan_repo: Path) -> None:
    def factory(name: str, config: ProjectConfig) -> FakeProvider:
        raise ValueError(f"Unknown provider: {name}")

    store = Store(plan_repo)
    with pytest.raises(ValueError, match="Unknown provider"):
        PlanRunner(plan_repo, factory).create(store, spec_of(node("a", ["files/a.txt"])))
    assert not (plan_repo / ".engineering" / "worktrees").exists()
    assert git(plan_repo, "branch", "--list", "eng/plan/*") == ""
    store.close()


def test_create_requires_clean_checkout(plan_repo: Path) -> None:
    (plan_repo / "dirty.txt").write_text("x", encoding="utf-8")
    runner = make_runner(plan_repo, NodeProvider({}, Tracker()))
    store = Store(plan_repo)
    with pytest.raises(ValueError, match="clean"):
        runner.create(store, spec_of(node("a", ["files/a.txt"])))
    store.close()


def test_create_refuses_a_project_without_confirmed_required_checks(plan_repo: Path) -> None:
    runner = make_runner(plan_repo, NodeProvider({}, Tracker()))
    store = Store(plan_repo)
    unconfirmed = ProjectConfig(
        checks=[Check(name="files", argv=["{python}", "check.py"], confirmed=False)]
    )
    with pytest.raises(ValueError, match="confirmed required check"):
        runner.create(store, spec_of(node("a", ["files/a.txt"])), unconfirmed)
    optional = ProjectConfig(
        checks=[Check(name="files", argv=["x"], confirmed=True, required=False)]
    )
    with pytest.raises(ValueError, match="confirmed required check"):
        runner.create(store, spec_of(node("a", ["files/a.txt"])), optional)
    assert git(plan_repo, "branch", "--list", "eng/plan/*") == ""
    store.close()


def test_large_plan_never_exceeds_three_and_integrates_everything(plan_repo: Path) -> None:
    tracker = Tracker()
    names = [f"n{i}" for i in range(10)]
    edits = {name: file_edit(name) for name in [*names, "t1", "t2", "t3"]}
    nodes = [node(name, [f"files/{name}.txt"]) for name in names]
    nodes += [
        node("t1", ["files/t1.txt"], ["n0", "n1"]),
        node("t2", ["files/t2.txt"], ["t1"]),
        node("t3", ["files/t3.txt"], ["n9", "t2"]),
    ]
    provider = NodeProvider(edits, tracker, delay=0.15)
    _, store, plan = run_plan(plan_repo, spec_of(*nodes, concurrency=3), provider)
    assert plan.status == PlanStatus.READY, plan.message
    assert node_concurrency(store, plan.id) == 3  # saturated at the cap, never above it
    assert tracker.peak <= 3
    tree = set(git(plan_repo, "ls-tree", "-r", "--name-only", plan.branch).splitlines())
    assert {f"files/{n}.txt" for n in edits} <= tree
    log = git(plan_repo, "log", "--format=%s", plan.branch).splitlines()
    assert sum("integrate" in line for line in log) == 13  # one commit per node
    store.close()


def test_two_plans_share_the_project_wide_slot_cap(plan_repo: Path) -> None:
    tracker = Tracker()
    names = ["a", "b", "c", "d", "e", "f"]
    provider = NodeProvider({n: file_edit(n) for n in names}, tracker, delay=0.4)
    runner = make_runner(plan_repo, provider)
    store = Store(plan_repo)
    first = runner.create(
        store, spec_of(*[node(n, [f"files/{n}.txt"]) for n in names[:3]], concurrency=3)
    )
    second_runner = make_runner(plan_repo, provider)
    second = second_runner.create(
        store, spec_of(*[node(n, [f"files/{n}.txt"]) for n in names[3:]], concurrency=3)
    )
    results: dict[str, PlanRecord] = {}
    threads = [
        threading.Thread(target=lambda r=r, p=p: results.__setitem__(p.id, r.run(p.id)))
        for r, p in ((runner, first), (second_runner, second))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert {r.status for r in results.values()} == {PlanStatus.READY}
    assert tracker.peak <= 3  # two coordinators, one shared cap
    merged = sorted(
        (e for p in (first, second) for e in store.plan_events(p.id)), key=lambda e: e["at"]
    )
    running = peak = 0
    for event in merged:
        if event["kind"] == "node_started":
            running += 1
            peak = max(peak, running)
        elif event["kind"] == "node_finished":
            running -= 1
    assert 2 <= peak <= 3  # combined in-flight nodes across both plans
    store.close()


def test_unusual_filenames_survive_ownership_and_integration(plan_repo: Path) -> None:
    name = "files/my file é.txt"
    edits = {"odd": {name: "MY FILE É"}}
    spec = spec_of(node("odd", [name]))
    _, store, plan = run_plan(plan_repo, spec, NodeProvider(edits, Tracker()))
    assert plan.status == PlanStatus.READY, plan.message
    listing = git(plan_repo, "ls-tree", "-r", "--name-only", "-z", plan.branch)
    assert name in listing.split("\0")
    store.close()


def test_conflict_report_names_the_conflicting_files(plan_repo: Path) -> None:
    from eng.execution.integrate import merge_tree, snapshot_commit

    base = head(plan_repo)
    scratch = plan_repo / ".engineering" / "artifacts" / "scratch"

    def variant(content: str) -> str:
        path = plan_repo / "files" / "seed.txt"
        original = path.read_text(encoding="utf-8")
        path.write_text(content, encoding="utf-8")
        try:
            return snapshot_commit(plan_repo, base, scratch, f"v-{content}")
        finally:
            path.write_text(original, encoding="utf-8")

    outcome = merge_tree(plan_repo, variant("LEFT"), variant("RIGHT"), base)
    assert not outcome.clean and outcome.conflicts == ["files/seed.txt"]
    assert merge_tree(plan_repo, variant("SAME"), variant("SAME"), base).clean


def test_starved_coordinator_waits_instead_of_abandoning_ready_work(plan_repo: Path) -> None:
    provider = NodeProvider({"a": file_edit("a")}, Tracker())
    runner = make_runner(plan_repo, provider)
    store = Store(plan_repo)
    plan = runner.create(store, spec_of(node("a", ["files/a.txt"])))
    pool = SlotPool(plan_repo)
    held = [pool.acquire() for _ in range(3)]  # another plan/verification owns every slot
    assert all(handle is not None for handle in held)
    result: dict[str, PlanRecord] = {}
    thread = threading.Thread(target=lambda: result.update(done=runner.run(plan.id)))
    thread.start()
    thread.join(timeout=1.5)
    assert thread.is_alive(), "the coordinator gave up while ready work was starved of slots"
    assert store.load_plan(plan.id).node("a").task_id is None  # nothing started yet
    for handle in held:
        pool.release(handle)  # type: ignore[arg-type]
    thread.join(timeout=60)
    assert result["done"].status == PlanStatus.READY
    assert "waiting_for_slot" in [e["kind"] for e in store.plan_events(plan.id)]
    store.close()

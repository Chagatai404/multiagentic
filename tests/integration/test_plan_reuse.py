"""E2: dependency handoffs, durable summary index and human plan attestations."""

import asyncio
import json
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from eng.cli import app
from eng.core.engine import Engine
from eng.core.models import PlanAttestation, ProviderRequest, ProviderResult, Role, State
from eng.core.plan import NodeStatus, PlanSpec
from eng.core.reuse import handoff_digest
from eng.execution.workspace import git
from eng.projects.config import load_config
from eng.providers.fake import FakeProvider
from eng.scheduling.runner import PlanRunner
from eng.storage.store import Store


class RecordingProvider(FakeProvider):
    """Per-node fixture edits keyed by NODE:<id>; records every role prompt."""

    def __init__(self, edits: dict[str, dict[str, str]]) -> None:
        super().__init__()
        self.edits = edits
        self.calls: list[tuple[str, Role, str]] = []
        self.lock = threading.Lock()

    async def execute(
        self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
    ) -> ProviderResult:
        match = re.search(r"NODE:(\w+)", request.prompt)
        assert match, "prompt must name its node"
        with self.lock:
            self.calls.append((match.group(1), request.role, request.prompt))
        if request.role in {Role.PLANNER, Role.REVIEWER}:
            return await super().execute(request, artifact_dir, cancelled)
        for relative, content in self.edits.get(match.group(1), {}).items():
            target = request.workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return ProviderResult(status="success", summary=f"implemented {match.group(1)}")

    def roles(self, node_id: str) -> list[Role]:
        return [role for node, role, _ in self.calls if node == node_id]

    def prompt(self, node_id: str, role: Role) -> str:
        return next(p for node, r, p in self.calls if node == node_id and r == role)


def node(
    node_id: str, owns: list[str], depends_on: list[str] | None = None, **extra: Any
) -> dict[str, Any]:
    return {
        "id": node_id,
        "description": f"NODE:{node_id} complex change",
        "acceptance": ["checks pass"],
        "owns": owns,
        "depends_on": depends_on or [],
        **extra,
    }


def spec_of(*nodes: dict[str, Any], **extra: Any) -> PlanSpec:
    return PlanSpec.model_validate(
        {
            "name": "reuse",
            "nodes": list(nodes),
            "provider": "fake",
            "node_budgets": {"model_calls": 6},
            **extra,
        }
    )


def runner_for(repo: Path, provider: FakeProvider) -> PlanRunner:
    return PlanRunner(repo, lambda name, config: provider, poll_seconds=0.02)


def events(store: Store, plan_id: str, kind: str) -> list[dict[str, Any]]:
    return [
        json.loads(event["payload"])
        for event in store.plan_events(plan_id)
        if event["kind"] == kind
    ]


EDITS = {
    "a": {"files/a.txt": "A", "files/a.md": "v1"},
    "b": {"files/b.txt": "B", "files/a.md": "v2"},
    "c": {"files/c.txt": "C"},
}


def test_dependency_handoffs_are_recorded_validated_and_rendered(plan_repo: Path) -> None:
    provider = RecordingProvider(EDITS)
    runner, store = runner_for(plan_repo, provider), Store(plan_repo)
    spec = spec_of(
        node("a", ["files/a.txt", "files/a.md"], interfaces=["files/a.txt holds A"]),
        node("b", ["files/b.txt", "files/a.md"], ["a"]),
        node("c", ["files/c.txt"], ["a", "b"]),
        context_reuse=True,
    )
    plan = runner.run(runner.create(store, spec).id)
    assert {n.status for n in plan.nodes} == {NodeStatus.INTEGRATED}

    # Durable summary index: persisted on the plan record, digest-bound to the node.
    saved = Store(plan_repo).load_plan(plan.id)
    a_handoff = saved.node("a").handoff
    assert a_handoff is not None
    assert a_handoff.changed_files == ["files/a.md", "files/a.txt"]
    assert a_handoff.summary == "implemented a"
    assert a_handoff.review_verdict == "pass"
    assert a_handoff.integrated_commit == saved.node("a").integrated_commit

    # Dependents see compact typed handoffs; c also learns a.md was changed again by b.
    b_prompt = provider.prompt("b", Role.ENGINEER)
    assert "Dependency handoff a" in b_prompt and "Provides: files/a.txt holds A" in b_prompt
    assert "Changed again" not in b_prompt
    c_prompt = provider.prompt("c", Role.PLANNER)
    assert "Dependency handoff a" in c_prompt and "Dependency handoff b" in c_prompt
    assert "Changed again after integration (read current content): files/a.md" in c_prompt
    assert "Dependency handoff" not in provider.prompt("a", Role.ENGINEER)

    manifests = {m["node"]: m for m in events(store, plan.id, "context_manifest")}
    assert manifests["a"]["dependencies"] == []
    c_dependencies = {d["node"]: d for d in manifests["c"]["dependencies"]}
    assert c_dependencies["a"]["stale_files"] == ["files/a.md"]
    assert c_dependencies["b"]["digest"] == saved.node("b").handoff.digest  # type: ignore[union-attr]
    task_c = store.load(saved.node("c").task_id or "")
    assert [h.node_id for h in task_c.spec.dependency_handoffs] == ["a", "b"]


def test_reuse_off_is_the_uncached_path(plan_repo: Path) -> None:
    provider = RecordingProvider(EDITS)
    runner, store = runner_for(plan_repo, provider), Store(plan_repo)
    plan = runner.run(
        runner.create(
            store,
            spec_of(node("a", ["files/a.txt", "files/a.md"]), node("c", ["files/c.txt"], ["a"])),
        ).id
    )
    assert {n.status for n in plan.nodes} == {NodeStatus.INTEGRATED}
    assert not any("Dependency handoff" in prompt for _, _, prompt in provider.calls)
    assert not events(store, plan.id, "context_manifest")
    task = store.load(plan.node("c").task_id or "")
    assert task.spec.dependency_handoffs == [] and task.spec.plan_attestation is None
    # The index is still recorded: it costs no model call and supports later reuse.
    assert plan.node("a").handoff is not None


def test_tampered_or_policy_stale_handoffs_are_omitted(plan_repo: Path) -> None:
    provider = RecordingProvider(EDITS)
    runner, store = runner_for(plan_repo, provider), Store(plan_repo)
    spec = spec_of(
        node("a", ["files/a.txt", "files/a.md"]),
        node("c", ["files/c.txt"], ["a"]),
        context_reuse=True,
    )
    plan = runner.create(store, spec)
    runner.run(plan.id)
    plan = store.load_plan(plan.id)
    handoff = plan.node("a").handoff
    assert handoff is not None
    plan.node("a").handoff = handoff.model_copy(update={"summary": "forged"})
    reused, _ = runner._reuse(store, plan, plan.node("c"), load_config(plan_repo))
    assert reused == []
    manifest = events(store, plan.id, "context_manifest")[-1]
    assert manifest["dependencies"] == [{"node": "a", "omitted": "handoff digest mismatch"}]
    plan.node("a").handoff = handoff
    changed = load_config(plan_repo).model_copy(update={"protected_paths": []})
    assert runner._reuse(store, plan, plan.node("c"), changed)[0] == []
    assert "policy" in events(store, plan.id, "context_manifest")[-1]["dependencies"][0]["omitted"]


def test_attestation_replaces_only_the_initial_planner_call(plan_repo: Path) -> None:
    spec = spec_of(node("a", ["files/a.txt", "files/a.md"]), node("c", ["files/c.txt"], ["a"]))
    baseline = RecordingProvider(EDITS)
    runner, store = runner_for(plan_repo, baseline), Store(plan_repo)
    unattested = runner.run(runner.create(store, spec).id)
    assert baseline.roles("c") == [Role.PLANNER, Role.ENGINEER, Role.REVIEWER]

    provider = RecordingProvider(EDITS)
    runner = runner_for(plan_repo, provider)
    plan = runner.create(store, spec)
    attested = runner.attest(store, plan.id, ["a", "c"])
    assert all(n.attestation is not None for n in attested.nodes)
    plan = runner.run(plan.id)
    assert {n.status for n in plan.nodes} == {NodeStatus.INTEGRATED}
    # No planner calls; engineer, deterministic checks and independent review remain.
    assert provider.roles("a") == [Role.ENGINEER, Role.REVIEWER]
    assert provider.roles("c") == [Role.ENGINEER, Role.REVIEWER]
    task = store.load(plan.node("c").task_id or "")
    assert task.state == State.COMPLETED and task.planning_completed and task.review_passed
    assert task.handoffs[0].role == Role.PLANNER
    assert task.handoffs[0].invocation_id.startswith("attestation:")
    assert [r.role for r in store.invocations(task.id)] == [Role.ENGINEER, Role.REVIEWER]
    assert "Previous planner handoff" in provider.prompt("c", Role.ENGINEER)
    kinds = [event["kind"] for event in store.events(task.id)]
    assert "planning_attested" in kinds
    unattested_task = store.load(unattested.node("c").task_id or "")
    assert len(store.invocations(unattested_task.id)) == 3
    assert [e["node"] for e in events(store, plan.id, "plan_attested")] == ["a", "c"]
    with pytest.raises(ValueError, match="already completed planning"):
        runner.attest(store, plan.id, ["c"], revoke=True)
    assert store.load_plan(plan.id).node("c").attestation is not None  # kept for audit


def test_revoking_a_launched_unplanned_node_clears_its_task_atomically(plan_repo: Path) -> None:
    provider = RecordingProvider(EDITS)
    runner, store = runner_for(plan_repo, provider), Store(plan_repo)
    plan = runner.create(
        store,
        spec_of(node("a", ["files/a.txt", "files/a.md"]), node("c", ["files/c.txt"], ["a"])),
    )
    plan = runner.attest(store, plan.id, ["a", "c"])
    _, attestation = runner._reuse(store, plan, plan.node("a"), load_config(plan_repo))
    assert attestation is not None
    task = runner._new_task(
        plan, plan.node("a"), load_config(plan_repo), False, attestation=attestation
    )
    store.create(task)
    plan.node("a").task_id = task.id
    store.save_plan(plan)
    # A consumed attestation on another node makes the whole request fail first.
    finished = task.model_copy(deep=True)
    finished.id, finished.planning_completed = "x" * 32, True
    store.create(finished)
    plan.node("c").task_id = finished.id
    store.save_plan(plan)
    with pytest.raises(ValueError, match="already completed planning"):
        runner.attest(store, plan.id, ["a", "c"], revoke=True)
    assert store.load(task.id).spec.plan_attestation is not None
    assert store.load_plan(plan.id).node("a").attestation is not None
    revoked = runner.attest(store, plan.id, ["a"], revoke=True)
    assert revoked.node("a").attestation is None
    assert store.load(task.id).spec.plan_attestation is None
    assert "attestation_revoked" in [e["kind"] for e in store.events(task.id)]


def test_attestation_is_invalidated_when_owned_paths_change_before_launch(
    plan_repo: Path,
) -> None:
    provider = RecordingProvider(
        {"a": {"files/a.txt": "A", "files/b.md": "early"}, "b": EDITS["b"]}
    )
    runner, store = runner_for(plan_repo, provider), Store(plan_repo)
    spec = spec_of(
        node("a", ["files/a.txt", "files/b.md"]),
        node("b", ["files/b.txt", "files/b.md", "files/a.md"], ["a"]),
    )
    plan = runner.create(store, spec)
    runner.attest(store, plan.id, ["a", "b"])
    plan = runner.run(plan.id)
    assert {n.status for n in plan.nodes} == {NodeStatus.INTEGRATED}
    assert provider.roles("a") == [Role.ENGINEER, Role.REVIEWER]
    assert provider.roles("b") == [Role.PLANNER, Role.ENGINEER, Role.REVIEWER]
    (invalidated,) = events(store, plan.id, "attestation_invalidated")
    assert invalidated["node"] == "b"
    assert invalidated["reason"] == "owned paths changed since attestation: files/b.md"
    assert store.load(plan.node("b").task_id or "").spec.plan_attestation is None


def test_unknown_revisions_invalidate_reuse_without_crashing(plan_repo: Path) -> None:
    provider = RecordingProvider(EDITS)
    runner, store = runner_for(plan_repo, provider), Store(plan_repo)
    spec = spec_of(
        node("a", ["files/a.txt", "files/a.md"]),
        node("c", ["files/c.txt"], ["a"]),
        context_reuse=True,
    )
    plan = runner.run(runner.create(store, spec).id)
    handoff = plan.node("a").handoff
    assert handoff is not None
    missing = "f" * 40
    forged = handoff.model_copy(update={"integrated_commit": missing})
    plan.node("a").handoff = forged.model_copy(update={"digest": handoff_digest(forged)})
    attested = runner.attest(store, runner.create(store, spec).id, ["c"]).node("c").attestation
    assert attested is not None
    plan.node("c").attestation = attested.model_copy(
        update={"plan_id": plan.id, "revision": missing}
    )
    handoffs, attestation = runner._reuse(store, plan, plan.node("c"), load_config(plan_repo))
    assert handoffs == [] and attestation is None
    manifest = events(store, plan.id, "context_manifest")[-1]
    assert manifest["dependencies"][0]["omitted"].startswith("revision check failed")
    (invalidated,) = events(store, plan.id, "attestation_invalidated")
    assert invalidated["reason"].startswith("revision check failed")


def test_engine_rejects_an_attestation_that_does_not_match_the_task(plan_repo: Path) -> None:
    provider = RecordingProvider(EDITS)
    runner, store = runner_for(plan_repo, provider), Store(plan_repo)
    plan = runner.create(store, spec_of(node("a", ["files/a.txt", "files/a.md"])))
    forged = PlanAttestation(
        plan_id=plan.id,
        node_id="a",
        scope_digest="0" * 64,
        policy_digest="0" * 64,
        revision=plan.head_commit,
    )
    task = runner._new_task(plan, plan.node("a"), load_config(plan_repo), False, attestation=forged)
    store.create(task)
    result = asyncio.run(Engine(store, provider).execute(task.id))
    assert result.state == State.COMPLETED
    assert provider.roles("a") == [Role.PLANNER, Role.ENGINEER, Role.REVIEWER]
    rejected = [e for e in store.events(task.id) if e["kind"] == "attestation_rejected"]
    assert rejected and "scope" in json.loads(rejected[0]["payload"])["reason"]


def test_attestation_is_refused_for_high_risk_or_launched_nodes_and_revocable(
    plan_repo: Path,
) -> None:
    provider = RecordingProvider(EDITS)
    runner, store = runner_for(plan_repo, provider), Store(plan_repo)
    spec = spec_of(
        node("a", ["files/a.txt", "files/a.md"]),
        node("h", ["files/h.txt"], risk="high"),
    )
    plan = runner.create(store, spec)
    with pytest.raises(ValueError, match="high-risk"):
        runner.attest(store, plan.id, ["h"])
    with pytest.raises(ValueError, match="at least one node"):
        runner.attest(store, plan.id, [])
    runner.attest(store, plan.id, ["a"])
    revoked = runner.attest(store, plan.id, ["a"], revoke=True)
    assert revoked.node("a").attestation is None
    assert events(store, plan.id, "attestation_revoked")[0]["node"] == "a"
    plan = runner.run(plan.id)
    assert plan.node("a").status == NodeStatus.INTEGRATED
    assert provider.roles("a")[0] == Role.PLANNER
    with pytest.raises(ValueError, match="already launched"):
        runner.attest(store, plan.id, ["a"])


def test_cli_attest_all_skips_high_risk_and_launched_nodes(plan_repo: Path) -> None:
    plan_file = plan_repo.parent / "plan.yaml"
    plan_file.write_text(
        yaml.safe_dump(
            spec_of(node("a", ["files/a.txt"]), node("h", ["files/h.txt"], risk="high")).model_dump(
                mode="json", exclude_none=True
            )
        ),
        encoding="utf-8",
    )
    cli = CliRunner()
    created = cli.invoke(app, ["plan", "create", str(plan_file), "--project", str(plan_repo)])
    assert created.exit_code == 0, created.output
    plan_id = json.loads(created.output)["id"]
    attested = cli.invoke(app, ["plan", "attest", plan_id, "--all", "--project", str(plan_repo)])
    assert attested.exit_code == 0, attested.output
    nodes = {n["spec"]["id"]: n for n in json.loads(attested.output)["nodes"]}
    assert nodes["a"]["attestation"]["source"] == "explicit_cli"
    assert nodes["h"]["attestation"] is None
    refused = cli.invoke(app, ["plan", "attest", plan_id, "h", "--project", str(plan_repo)])
    assert refused.exit_code != 0
    revoked = cli.invoke(
        app, ["plan", "attest", plan_id, "--all", "--revoke", "--project", str(plan_repo)]
    )
    assert revoked.exit_code == 0, revoked.output
    assert all(n["attestation"] is None for n in json.loads(revoked.output)["nodes"])
    assert git(plan_repo, "status", "--porcelain", "--untracked-files=normal") == ""

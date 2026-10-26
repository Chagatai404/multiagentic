"""Serialized, verified integration of completed plan nodes and approval-gated promotion.

Integration is the second completion gate: a node that passed its own task gates is
merged into the eng-owned plan branch only if ownership and protected-path rules hold,
the merge is conflict free, and the project's required checks pass on the integrated
tree. Any failure restores the previous verified head. Promotion into the user's branch
is a separate, explicitly approved fast-forward; eng never pushes.
"""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from eng.core.models import State, Task
from eng.core.plan import NodeStatus, PlanNode, PlanRecord, PlanStatus, outside_ownership
from eng.core.policy import completion_gate
from eng.core.reuse import build_dependency_handoff
from eng.execution.integrate import (
    changed_between,
    commit_tree,
    current_branch,
    fast_forward,
    head,
    is_ancestor,
    merge_tree,
    reset_integration,
    snapshot_commit,
)
from eng.execution.process import redact
from eng.execution.workspace import git, protected_changes
from eng.storage.store import Store
from eng.verification.runner import run_checks


def plan_artifacts(plan: PlanRecord) -> Path:
    return plan.project / ".engineering" / "artifacts" / "plans" / plan.id


def reconcile(store: Store, plan: PlanRecord) -> None:
    """Restore the integration worktree to the last recorded verified head.

    A crash between moving the branch and saving the plan would otherwise leave an
    unverified commit on the branch. Nodes still VERIFIED are simply integrated again.
    """
    if not plan.workspace.is_dir():
        raise ValueError("Integration workspace is missing; inspect the plan before continuing")
    if head(plan.workspace) != plan.head_commit or git(
        plan.workspace, "status", "--porcelain", "--untracked-files=normal"
    ):
        store.plan_event(plan.id, "integration_reconciled", {"restored": plan.head_commit})
        reset_integration(plan.workspace, plan.head_commit)


def _block(store: Store, plan: PlanRecord, node: PlanNode, message: str, kind: str) -> bool:
    node.status = NodeStatus.BLOCKED
    node.message = redact(message)
    plan.final_verified = False
    store.plan_event(plan.id, kind, {"node": node.spec.id, "message": node.message})
    store.save_plan(plan)
    return False


def integrate_node(
    store: Store, plan: PlanRecord, node: PlanNode, cancelled: Callable[[], bool]
) -> bool:
    """Integrate one VERIFIED node; True when the plan head advanced and verified."""
    assert node.task_id is not None
    task: Task = store.load(node.task_id)
    if task.state != State.COMPLETED or task.workspace is None or task.base_commit is None:
        return _block(store, plan, node, "Node task is not completed", "integration_refused")
    scratch = plan_artifacts(plan) / node.spec.id
    try:
        if head(task.workspace) != task.base_commit:
            return _block(store, plan, node, "Node workspace HEAD changed", "integration_refused")
        node.node_commit = snapshot_commit(
            task.workspace, task.base_commit, scratch, f"eng plan {plan.id[:8]} node {node.spec.id}"
        )
        paths = changed_between(plan.project, task.base_commit, node.node_commit)
        forbidden = protected_changes(paths, task.config.protected_paths)
        outside = outside_ownership(paths, node.spec.owns)
        if forbidden or outside:
            detail = ", ".join([*forbidden, *outside])
            return _block(
                store,
                plan,
                node,
                "Node changes violate ownership or protected paths: " + detail,
                "integration_refused",
            )
        merged = merge_tree(plan.workspace, plan.head_commit, node.node_commit, task.base_commit)
        if not merged.clean or merged.tree is None:
            return _block(
                store,
                plan,
                node,
                "Merge conflict in: " + ", ".join(merged.conflicts),
                "integration_conflict",
            )
        previous = plan.head_commit
        candidate = commit_tree(
            plan.workspace,
            merged.tree,
            previous,
            f"eng plan {plan.id[:8]}: integrate {node.spec.id}",
        )
        plan.final_verified = False
        store.save_plan(plan)
        reset_integration(plan.workspace, candidate)
        try:
            results = asyncio.run(
                run_checks(
                    plan.workspace,
                    task.config.checks,
                    scratch / "integration-checks",
                    cancelled,
                    task.spec.budgets.wall_seconds,
                )
            )
            accepted, reason = completion_gate(results)
        except BaseException:
            reset_integration(plan.workspace, previous)
            raise
        plan.final_verification = results
        store.plan_event(
            plan.id,
            "integration_verified" if accepted else "integration_failed",
            {"node": node.spec.id, "accepted": accepted, "reason": reason},
        )
        if not accepted:
            reset_integration(plan.workspace, previous)
            return _block(
                store,
                plan,
                node,
                "Integrated tree failed verification: " + reason,
                "integration_rolled_back",
            )
    except (ValueError, OSError) as error:
        return _block(store, plan, node, f"Integration failed: {error}", "integration_error")
    plan.head_commit = candidate
    node.integrated_commit = candidate
    assert node.node_commit is not None
    node.handoff = build_dependency_handoff(
        node_id=node.spec.id,
        task=task,
        node_commit=node.node_commit,
        integrated_commit=candidate,
        changed_files=paths,
        interfaces=node.spec.interfaces,
    )
    node.status = NodeStatus.INTEGRATED
    node.message = "Integrated and verified"
    plan.final_verified = True
    store.plan_event(
        plan.id, "node_integrated", {"node": node.spec.id, "head": candidate, "paths": paths}
    )
    store.save_plan(plan)
    return True


def promotion_report(plan: PlanRecord) -> dict[str, Any]:
    """Evaluate every promotion precondition without changing anything."""
    problems: list[str] = []
    if plan.status == PlanStatus.PROMOTED:
        problems.append("Plan is already promoted")
    elif plan.status != PlanStatus.READY:
        problems.append(f"Plan is {plan.status.value}; every node must be integrated")
    if not plan.final_verified:
        problems.append("The integrated head has no passing verification")
    root = plan.project
    try:
        if head(root, plan.branch) != plan.head_commit:
            problems.append("Plan branch moved since its last verification")
        if git(root, "status", "--porcelain", "--untracked-files=normal"):
            problems.append("Checkout has uncommitted changes")
        branch = current_branch(root)
        if branch is None:
            problems.append("Checkout is on a detached HEAD; check out a branch first")
        if not is_ancestor(root, "HEAD", plan.head_commit):
            problems.append(
                "Current branch is not an ancestor of the plan head; not a fast-forward"
            )
        forbidden = protected_changes(
            changed_between(root, plan.base_commit, plan.head_commit),
            [".git", ".engineering", ".env", ".env.*", "*.pem", "*.key"],
        )
        if forbidden:
            problems.append("Plan touches protected paths: " + ", ".join(forbidden))
    except ValueError as error:
        branch = None
        problems.append(f"Cannot inspect repository: {error}")
    return {
        "plan_id": plan.id,
        "branch": plan.branch,
        "plan_head": plan.head_commit,
        "target_branch": branch,
        "promotable": not problems,
        "problems": problems,
    }


def promote(store: Store, plan: PlanRecord, *, approved: bool) -> dict[str, Any]:
    """Fast-forward the user's branch to the verified plan head after explicit approval."""
    report = promotion_report(plan)
    report["approved"] = approved
    report["promoted"] = False
    if not report["promotable"] or not approved:
        if report["promotable"]:
            report["next"] = "Re-run with --approve to fast-forward the target branch"
        return report
    store.plan_event(plan.id, "promotion_approved", {"source": "explicit_cli"})
    fast_forward(plan.project, plan.head_commit)
    if head(plan.project) != plan.head_commit:
        raise ValueError("Fast-forward did not reach the verified plan head")
    plan.promoted_commit = plan.head_commit
    plan.status = PlanStatus.PROMOTED
    plan.message = "Promoted by explicit approval; nothing was pushed"
    store.plan_event(plan.id, "promoted", {"commit": plan.head_commit})
    store.save_plan(plan)
    report["promoted"] = True
    return report

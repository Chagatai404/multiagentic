"""Pure E2 context/plan reuse policy: digests, validation and rendering.

Reuse is never trusted on its own. Every reused item binds the scope it describes, the
project verification policy and a Git revision; the imperative callers (plan runner and
engine) check those bindings before use and fall back to the ordinary uncached path,
with an event, when any binding no longer holds. Nothing here waives independent
review, required checks, task approval, ownership or protected-path policy.
"""

import hashlib
import json
from collections.abc import Sequence

from eng.core.models import (
    Classification,
    DependencyHandoff,
    PlanAttestation,
    ProjectConfig,
    Risk,
    Role,
    RoleHandoff,
    Task,
    TaskSpec,
)
from eng.core.plan import PlanNodeSpec, node_description

MAX_HANDOFF_FILES = 50
MAX_HANDOFF_SUMMARY = 1000


def _digest(value: object) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scope_digest(
    *,
    description: str,
    acceptance: Sequence[str],
    owned_paths: Sequence[str],
    context_paths: Sequence[str],
    risk: Risk | None,
    interfaces: Sequence[str],
) -> str:
    """Digest of everything an attested node's packet promises the engineer."""
    return _digest(
        {
            "description": description,
            "acceptance": list(acceptance),
            "owned_paths": list(owned_paths),
            "context_paths": list(context_paths),
            "risk": risk.value if risk is not None else None,
            "interfaces": list(interfaces),
        }
    )


def node_scope_digest(spec: PlanNodeSpec) -> str:
    return scope_digest(
        description=node_description(spec),
        acceptance=spec.acceptance,
        owned_paths=spec.owns,
        context_paths=spec.context_paths,
        risk=spec.risk,
        interfaces=spec.interfaces,
    )


def task_scope_digest(spec: TaskSpec) -> str:
    return scope_digest(
        description=spec.description,
        acceptance=spec.acceptance,
        owned_paths=spec.owned_paths,
        context_paths=spec.context_paths,
        risk=spec.classification_overrides.risk,
        interfaces=spec.interfaces,
    )


def policy_digest(config: ProjectConfig) -> str:
    """Verification policy fingerprint: checks, protected paths and instructions.

    Budgets and repair limits are excluded: plans legitimately resolve them per node.
    """
    return _digest(
        {
            "checks": [check.model_dump(mode="json") for check in config.checks],
            "protected_paths": config.protected_paths,
            "instructions": config.instructions,
        }
    )


def attestation_problem(
    attestation: PlanAttestation,
    spec: TaskSpec,
    config: ProjectConfig,
    classification: Classification | None,
) -> str | None:
    """Why an attestation cannot satisfy this task's planning step, or None."""
    if attestation.scope_digest != task_scope_digest(spec):
        return "task scope differs from the attested node scope"
    if attestation.policy_digest != policy_digest(config):
        return "project verification policy changed since attestation"
    if classification is None or classification.risk == Risk.HIGH:
        return "high-risk work keeps model planning"
    return None


def attested_planner_handoff(attestation: PlanAttestation) -> RoleHandoff:
    return RoleHandoff(
        role=Role.PLANNER,
        summary=(
            "Planning satisfied by human plan attestation: implement the objective, "
            "acceptance criteria and interface contracts exactly as specified."
        ),
        invocation_id=f"attestation:{attestation.id}",
        steps=[],
    )


def _handoff_fields(handoff: DependencyHandoff) -> dict[str, object]:
    return handoff.model_dump(mode="json", exclude={"digest", "stale_files"})


def handoff_digest(handoff: DependencyHandoff) -> str:
    return _digest(_handoff_fields(handoff))


def build_dependency_handoff(
    *,
    node_id: str,
    task: Task,
    node_commit: str,
    integrated_commit: str,
    changed_files: Sequence[str],
    interfaces: Sequence[str],
) -> DependencyHandoff:
    """Summarize a completed node from its own persisted role handoffs; no model call."""
    work = [h for h in task.handoffs if h.role in {Role.ENGINEER, Role.DEBUGGER}]
    review = [h for h in task.handoffs if h.role == Role.REVIEWER]
    files = sorted(changed_files)
    draft = DependencyHandoff(
        node_id=node_id,
        task_id=task.id,
        node_commit=node_commit,
        integrated_commit=integrated_commit,
        summary=work[-1].summary[:MAX_HANDOFF_SUMMARY] if work else "",
        review_verdict=review[-1].verdict if review else None,
        changed_files=files[:MAX_HANDOFF_FILES],
        files_truncated=len(files) > MAX_HANDOFF_FILES,
        interfaces=list(interfaces),
        policy_digest=policy_digest(task.config),
        digest="0" * 64,
    )
    draft.digest = handoff_digest(draft)
    return draft


def handoff_problem(handoff: DependencyHandoff, config: ProjectConfig) -> str | None:
    if handoff.digest != handoff_digest(handoff):
        return "handoff digest mismatch"
    if handoff.policy_digest != policy_digest(config):
        return "project verification policy changed since integration"
    return None


def render_dependency_handoff(handoff: DependencyHandoff) -> str:
    """Compact packet text; names files rather than pasting their content."""
    lines = [
        f"Node {handoff.node_id} integrated at {handoff.integrated_commit[:12]}"
        + (f"; review {handoff.review_verdict}" if handoff.review_verdict else ""),
    ]
    if handoff.summary:
        lines.append("Summary: " + handoff.summary)
    if handoff.interfaces:
        lines.append("Provides: " + "; ".join(handoff.interfaces))
    if handoff.changed_files:
        lines.append(
            "Changed files: "
            + ", ".join(handoff.changed_files)
            + (" (truncated)" if handoff.files_truncated else "")
        )
    if handoff.stale_files:
        lines.append(
            "Changed again after integration (read current content): "
            + ", ".join(handoff.stale_files)
        )
    return "\n".join(lines)

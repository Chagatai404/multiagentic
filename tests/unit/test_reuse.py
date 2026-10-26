from pathlib import Path

import pytest
from pydantic import ValidationError

from eng.core.models import (
    Check,
    Classification,
    ClassificationOverrides,
    Complexity,
    PlanAttestation,
    ProjectConfig,
    Risk,
    Role,
    RoleHandoff,
    Task,
    TaskSpec,
    TaskType,
)
from eng.core.plan import PlanNodeSpec, node_description
from eng.core.reuse import (
    attestation_problem,
    attested_planner_handoff,
    build_dependency_handoff,
    handoff_problem,
    node_scope_digest,
    policy_digest,
    render_dependency_handoff,
    task_scope_digest,
)

COMMIT = "a" * 40


def config(*argv: str) -> ProjectConfig:
    return ProjectConfig(
        checks=[Check(name="tests", argv=list(argv or ["pytest"]), confirmed=True)]
    )


def node(**extra: object) -> PlanNodeSpec:
    return PlanNodeSpec.model_validate(
        {
            "id": "api",
            "description": "complex change",
            "acceptance": ["tests pass"],
            "owns": ["src/api/**"],
            "context_paths": ["README.md"],
            "interfaces": ["eng.api.fetch(id) -> Record"],
            **extra,
        }
    )


def task_spec_for(spec: PlanNodeSpec) -> TaskSpec:
    return TaskSpec(
        description=node_description(spec),
        acceptance=spec.acceptance,
        owned_paths=spec.owns,
        context_paths=spec.context_paths,
        classification_overrides=ClassificationOverrides(risk=spec.risk),
        interfaces=spec.interfaces,
    )


def classification(risk: Risk = Risk.LOW) -> Classification:
    return Classification(task_type=TaskType.CHANGE, complexity=Complexity.COMPLEX, risk=risk)


def attestation(spec: PlanNodeSpec, project: ProjectConfig) -> PlanAttestation:
    return PlanAttestation(
        plan_id="p",
        node_id=spec.id,
        scope_digest=node_scope_digest(spec),
        policy_digest=policy_digest(project),
        revision=COMMIT,
    )


def test_node_and_task_scope_digests_agree_and_bind_every_scope_field() -> None:
    spec = node()
    assert node_scope_digest(spec) == task_scope_digest(task_spec_for(spec))
    variants: list[dict[str, object]] = [
        {"description": "complex change two"},
        {"acceptance": ["other"]},
        {"owns": ["src/other/**"]},
        {"context_paths": []},
        {"risk": "medium"},
        {"interfaces": ["eng.api.fetch(id, *, timeout) -> Record"]},
    ]
    digests = {node_scope_digest(node(**variant)) for variant in variants}
    assert len(digests) == len(variants) and node_scope_digest(spec) not in digests


def test_policy_digest_ignores_budgets_but_binds_checks_protection_and_instructions() -> None:
    base = config()
    relaxed = base.model_copy(deep=True)
    relaxed.budgets.model_calls = 9
    relaxed.workflow.max_repairs = 0
    assert policy_digest(relaxed) == policy_digest(base)
    assert policy_digest(config("pytest", "-k", "fast")) != policy_digest(base)
    unprotected = base.model_copy(update={"protected_paths": []})
    assert policy_digest(unprotected) != policy_digest(base)
    assert policy_digest(base.model_copy(update={"instructions": []})) != policy_digest(base)


def test_attestation_is_rejected_on_scope_policy_or_high_risk_changes() -> None:
    spec, project = node(), config()
    granted = attestation(spec, project)
    task = task_spec_for(spec)
    assert attestation_problem(granted, task, project, classification()) is None
    changed = task.model_copy(update={"acceptance": ["tests pass", "docs updated"]})
    assert "scope" in str(attestation_problem(granted, changed, project, classification()))
    assert "policy" in str(attestation_problem(granted, task, config("ruff"), classification()))
    assert "high-risk" in str(
        attestation_problem(granted, task, project, classification(Risk.HIGH))
    )
    assert "high-risk" in str(attestation_problem(granted, task, project, None))


def test_attested_planner_handoff_is_marked_and_not_a_provider_invocation() -> None:
    handoff = attested_planner_handoff(attestation(node(), config()))
    assert handoff.role == Role.PLANNER
    assert handoff.invocation_id.startswith("attestation:")


def completed_task(*handoffs: RoleHandoff) -> Task:
    spec = TaskSpec(description="x", acceptance=["y"])
    return Task(project=Path("."), spec=spec, config=config(), handoffs=list(handoffs))


def test_dependency_handoff_is_compact_digest_bound_and_policy_bound() -> None:
    task = completed_task(
        RoleHandoff(role=Role.ENGINEER, summary="first", invocation_id="1"),
        RoleHandoff(role=Role.DEBUGGER, summary="x" * 5000, invocation_id="2"),
        RoleHandoff(role=Role.REVIEWER, summary="ok", invocation_id="3", verdict="pass"),
    )
    files = [f"src/f{index:03}.py" for index in range(60)]
    handoff = build_dependency_handoff(
        node_id="api",
        task=task,
        node_commit=COMMIT,
        integrated_commit="b" * 40,
        changed_files=files,
        interfaces=["fetch()"],
    )
    assert handoff.summary == "x" * 1000
    assert handoff.review_verdict == "pass"
    assert len(handoff.changed_files) == 50 and handoff.files_truncated
    assert handoff_problem(handoff, config()) is None
    assert "policy" in str(handoff_problem(handoff, config("ruff")))
    tampered = handoff.model_copy(update={"summary": "trust me"})
    assert "digest" in str(handoff_problem(tampered, config()))
    # Consumer-specific staleness is outside the digest.
    stale = handoff.model_copy(update={"stale_files": ["src/f000.py"]})
    assert handoff_problem(stale, config()) is None
    text = render_dependency_handoff(stale)
    assert "Provides: fetch()" in text and "(truncated)" in text
    assert "Changed again after integration (read current content): src/f000.py" in text


def test_interface_contracts_are_bounded() -> None:
    with pytest.raises(ValidationError):
        node(interfaces=[" "])
    with pytest.raises(ValidationError):
        node(interfaces=["x" * 501])
    with pytest.raises(ValidationError):
        node(interfaces=[f"i{index}" for index in range(21)])

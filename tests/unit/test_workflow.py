from pathlib import Path

import pytest
from pydantic import ValidationError

from eng.core.models import (
    ClassificationOverrides,
    Complexity,
    ProjectConfig,
    Risk,
    Role,
    State,
    Task,
    TaskSpec,
    TaskType,
    VerificationResult,
    WorkflowPolicy,
)
from eng.core.policy import validate_transition
from eng.core.workflow import (
    classify_task,
    escalate_classification,
    failure_signature,
    select_workflow,
    workflow_completion_gate,
)


def spec(description: str = "Fix answer") -> TaskSpec:
    return TaskSpec(description=description, acceptance=["checks pass"])


def result(outcome: str = "PASS", **kwargs: object) -> VerificationResult:
    return VerificationResult.model_validate(
        {
            "check_id": "tests",
            "command": ["pytest"],
            "environment": "fixture",
            "outcome": outcome,
            **kwargs,
        }
    )


def task(description: str = "Fix answer") -> Task:
    request = spec(description)
    classification = classify_task(request)
    return Task(
        project=Path("."),
        spec=request,
        config=ProjectConfig(),
        classification=classification,
        workflow=select_workflow(classification, WorkflowPolicy()),
        verification=[result()],
    )


def test_old_json_defaults_and_independent_lists() -> None:
    old = '{"project":".","spec":{"description":"Fix answer","acceptance":["ok"]},"config":{}}'
    first = Task.model_validate_json(old)
    second = Task.model_validate_json(old)
    assert first.classification is None and first.workflow is None
    assert first.config.workflow.max_repairs == 2
    assert first.spec.budgets.model_calls == 1
    assert not first.spec.human_approved
    assert first.spec.classification_overrides == ClassificationOverrides()
    first.repairs.clear()
    first.next_role = Role.REVIEWER
    assert second.next_role is None
    assert second.handoffs == second.repairs == []
    assert Task.model_validate_json(first.model_dump_json()) == first


@pytest.mark.parametrize("description", ["Fix answer", "Repair answer"])
def test_legacy_simple_work_is_one_engineer(description: str) -> None:
    classification = classify_task(spec(description))
    assert classification.complexity == Complexity.SMALL
    assert classification.risk == Risk.LOW
    workflow = select_workflow(classification, WorkflowPolicy())
    assert not workflow.planner and not workflow.reviewer and not workflow.approval_required
    assert workflow.max_repairs == 2


@pytest.mark.parametrize(
    ("description", "complexity", "risk"),
    [
        ("Fix authentication typo", Complexity.SMALL, Risk.HIGH),
        ("Redesign architecture of formatting", Complexity.COMPLEX, Risk.LOW),
        ("Update database field", Complexity.SMALL, Risk.MEDIUM),
        ("Refactor helper", Complexity.MEDIUM, Risk.LOW),
    ],
)
def test_axes_are_independent(description: str, complexity: Complexity, risk: Risk) -> None:
    classification = classify_task(spec(description))
    assert classification.complexity == complexity
    assert classification.risk == risk


def test_overrides_cannot_downgrade_safeguards_even_for_question() -> None:
    request = spec("Redesign authentication architecture")
    request.classification_overrides = ClassificationOverrides(
        task_type=TaskType.QUESTION,
        complexity=Complexity.SMALL,
        risk=Risk.LOW,
    )
    classification = classify_task(request)
    assert classification.task_type == TaskType.QUESTION
    assert classification.complexity == Complexity.COMPLEX
    assert classification.risk == Risk.HIGH
    workflow = select_workflow(classification, WorkflowPolicy())
    assert workflow.planner and workflow.reviewer and workflow.approval_required


def test_context_paths_and_raised_overrides() -> None:
    request = spec()
    request.context_paths = ["src/authentication/login.py"]
    assert classify_task(request).risk == Risk.HIGH
    request.context_paths = []
    request.classification_overrides = ClassificationOverrides(complexity=Complexity.COMPLEX)
    assert select_workflow(classify_task(request), WorkflowPolicy()).planner
    assert classify_task(spec("Why is the sky blue?")).task_type == TaskType.QUESTION
    assert classify_task(spec("Fix and explain answer")).task_type == TaskType.CHANGE


@pytest.mark.parametrize(
    "path",
    [
        "uv.lock",
        "package-lock.json",
        "sub/uv.lock",
        "sub/package-lock.json",
        "sub\\uv.lock",
        "sub\\package-lock.json",
    ],
)
def test_lockfile_context_paths_infer_compatibility_risk(path: str) -> None:
    request = spec()
    request.context_paths = [path]
    assert classify_task(request).risk == Risk.MEDIUM


@pytest.mark.parametrize(
    "description",
    [
        "How do I fix this bug?",
        "Explain how to implement X",
    ],
)
def test_question_prefix_does_not_authorize_edits(description: str) -> None:
    request = spec(description)
    assert classify_task(request).task_type == TaskType.QUESTION
    request.classification_overrides = ClassificationOverrides(task_type=TaskType.CHANGE)
    assert classify_task(request).task_type == TaskType.CHANGE
    assert classify_task(spec("Can you fix X")).task_type == TaskType.CHANGE


def test_observed_scope_only_escalates_and_preserves_task_type() -> None:
    current = classify_task(spec("Why is the sky blue?"))
    observed = classify_task(spec("Redesign authentication architecture"))
    raised = escalate_classification(current, observed)
    assert raised.task_type == TaskType.QUESTION
    assert raised.complexity == Complexity.COMPLEX and raised.risk == Risk.HIGH
    assert escalate_classification(raised, current) == raised


@pytest.mark.parametrize("limit", [-1, 11])
def test_repair_limits_are_bounded(limit: int) -> None:
    with pytest.raises(ValidationError):
        WorkflowPolicy(max_repairs=limit)


def test_gate_requires_checks_classification_planning_approval_and_current_review() -> None:
    simple = task()
    assert workflow_completion_gate(simple)[0]
    simple.verification = []
    assert not workflow_completion_gate(simple)[0]
    simple.verification = [result()]
    simple.classification = None
    assert not workflow_completion_gate(simple)[0]
    complex_task = task("Redesign authentication architecture")
    assert not workflow_completion_gate(complex_task)[0]
    complex_task.spec.human_approved = True
    assert not workflow_completion_gate(complex_task)[0]
    complex_task.planning_completed = True
    assert not workflow_completion_gate(complex_task)[0]
    complex_task.review_passed = True
    assert not workflow_completion_gate(complex_task)[0]
    complex_task.verified_digest = "current"
    complex_task.review_digest = "stale"
    assert not workflow_completion_gate(complex_task)[0]
    complex_task.review_digest = "current"
    assert workflow_completion_gate(complex_task)[0]
    complex_task.verification = [result("UNAVAILABLE")]
    assert not workflow_completion_gate(complex_task)[0]


def test_completion_recomputes_safeguards_and_rejects_questions() -> None:
    current = task("Fix authentication")
    assert current.workflow is not None
    current.workflow.approval_required = False
    current.workflow.reviewer = False
    assert not workflow_completion_gate(current)[0]
    question = task("Why is answer 42?")
    assert not workflow_completion_gate(question)[0]


def test_signature_ignores_duration_artifact_order_and_optional_checks() -> None:
    failed = result("FAIL", exit_code=1, reason="AssertionError")
    other = failed.model_copy(update={"check_id": "lint"})
    signature = failure_signature([failed, other])
    changed = failed.model_copy(
        update={
            "duration_seconds": 99,
            "artifact": "different.log",
            "environment": "other/worktree",
        }
    )
    optional = result("ERROR", required=False)
    assert signature == failure_signature([other, changed, optional])
    assert signature != failure_signature([failed.model_copy(update={"reason": "TypeError"})])


@pytest.mark.parametrize("outcome", ["ERROR", "SKIPPED", "UNAVAILABLE"])
def test_nonactionable_evidence_never_requests_repair(outcome: str) -> None:
    assert failure_signature([result("FAIL"), result(outcome)]) == ""
    assert failure_signature([result(outcome)]) == ""
    assert failure_signature([]) == failure_signature([result()]) == ""


@pytest.mark.parametrize("source", [State.PAUSED, State.BLOCKED])
@pytest.mark.parametrize(
    "target",
    [
        State.CLASSIFYING,
        State.PREPARING_CONTEXT,
        State.PLANNING,
        State.IMPLEMENTING,
        State.VERIFYING,
        State.REVIEWING,
        State.DEBUGGING,
    ],
)
def test_explicit_recovery_paths(source: State, target: State) -> None:
    validate_transition(source, target)


def test_question_approval_and_uncertain_plan_paths() -> None:
    validate_transition(State.CLASSIFYING, State.BLOCKED)
    validate_transition(State.CLASSIFYING, State.PAUSED)
    validate_transition(State.REVIEWING, State.BLOCKED)
    validate_transition(State.VERIFYING, State.PLANNING)


@pytest.mark.parametrize("target", [State.VERIFYING, State.REVIEWING, State.DEBUGGING])
def test_prepared_workspace_can_resume_saved_stage(target: State) -> None:
    validate_transition(State.PREPARING_CONTEXT, target)


def test_malformed_planner_output_can_block() -> None:
    validate_transition(State.PLANNING, State.BLOCKED)

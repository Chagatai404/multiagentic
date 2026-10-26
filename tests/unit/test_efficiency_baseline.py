"""Pre-change safeguards pinned before the E0/E1 implementation."""

import pytest

from eng.benchmark import _fixture
from eng.core.accounting import budget_stop_reason, usage_report
from eng.core.models import (
    Budgets,
    InvocationRecord,
    ProviderResult,
    Role,
    TaskSpec,
    Usage,
    VerificationResult,
    WorkflowPolicy,
)
from eng.core.policy import completion_gate
from eng.core.workflow import classify_task, select_workflow


def record(usage: Usage | None = None) -> InvocationRecord:
    return InvocationRecord(
        invocation_id="one",
        execution_id="execution",
        provider="fake",
        role=Role.ENGINEER,
        status="success",
        result=ProviderResult(status="success", usage=usage or Usage()),
    )


def test_no_telemetry_never_means_zero_cost_or_credit_balance() -> None:
    report = usage_report([record()])
    assert report.invocations == 1
    assert report.measured_account_spend is None
    group = report.groups[0]
    assert group.fields["input_tokens"].known_subtotal is None
    assert group.reported_cost_usd.known_subtotal is None
    assert group.pricing_estimate_usd.known_subtotal is None


def test_unknown_coverage_blocks_next_call_but_initial_call_has_no_estimate() -> None:
    budgets = Budgets(reported_input_tokens=10)
    assert budget_stop_reason([], budgets) is None
    assert "unknown" in (budget_stop_reason([record()], budgets) or "")
    assert "reached" in (budget_stop_reason([record(Usage(input_tokens=10))], budgets) or "")


@pytest.mark.parametrize(
    "description", ["Fix security permission bug", "Refactor complex architecture"]
)
def test_efficiency_preserves_independent_review(description: str) -> None:
    spec = TaskSpec(description=description, acceptance=["Pass checks"])
    decision = select_workflow(classify_task(spec), WorkflowPolicy())
    assert decision.reviewer
    assert decision.max_repairs == 2
    if "security" in description:
        assert decision.approval_required
    else:
        assert decision.planner


def test_no_required_checks_cannot_complete() -> None:
    assert completion_gate([])[0] is False


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("small_bug", "small"),
        ("medium_feature", "medium"),
        ("large_refactor", "complex"),
    ],
)
def test_benchmark_case_labels_match_actual_classification(scenario: str, expected: str) -> None:
    fixture = _fixture(scenario, 42)
    spec = TaskSpec(
        description=fixture.description, acceptance=["Pass"], context_paths=list(fixture.initial)
    )
    assert classify_task(spec).complexity.value == expected


@pytest.mark.parametrize("outcome", ["FAIL", "ERROR", "UNAVAILABLE", "SKIPPED"])
def test_nonpassing_required_evidence_never_completes(outcome: str) -> None:
    evidence = VerificationResult.model_validate(
        {
            "check_id": "required",
            "command": ["fake-check"],
            "environment": "offline",
            "outcome": outcome,
        }
    )
    assert completion_gate([evidence])[0] is False

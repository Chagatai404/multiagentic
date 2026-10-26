from pathlib import Path

import pytest
from pydantic import ValidationError

from eng.core.accounting import budget_stop_reason, estimate_cost, usage_report
from eng.core.models import (
    Budgets,
    InvocationRecord,
    PricingRule,
    ProjectConfig,
    ProviderResult,
    Role,
    Task,
    TaskSpec,
    Usage,
    identity,
)
from eng.storage.store import Store


def record(usage: Usage | None = None, *, model: str | None = "model") -> InvocationRecord:
    return InvocationRecord(
        invocation_id=identity(),
        execution_id=identity(),
        provider="fake",
        model=model,
        role=Role.ENGINEER,
        status="success" if usage else "started",
        result=ProviderResult(status="success", usage=usage) if usage else None,
    )


def test_field_coverage_cost_sources_and_model_groups_remain_separate() -> None:
    rows = [
        record(
            Usage(
                input_tokens=100,
                output_tokens=10,
                cached_input_tokens=50,
                cost_usd=0.3,
                cost_source="reported",
            )
        ),
        record(Usage(input_tokens=200, cost_usd=0.4, cost_source="client_estimate")),
        record(),
        record(Usage(input_tokens=0), model=None),
    ]
    report = usage_report(rows)
    group = report.groups[0]
    assert report.invocations == 4 and len(report.groups) == 2
    assert group.fields["input_tokens"].model_dump() == {
        "known_subtotal": 300,
        "reported": 2,
        "missing": 1,
    }
    assert group.fields["output_tokens"].missing == 2
    assert group.fields["cached_input_tokens"].known_subtotal == 50
    assert group.fields["reasoning_tokens"].known_subtotal is None
    assert group.reported_cost_usd.known_subtotal == 0.3
    assert group.reported_cost_usd.missing == 2
    assert group.client_estimate_cost_usd.known_subtotal == 0.4
    assert report.groups[1].fields["input_tokens"].known_subtotal == 0
    assert report.groups[1].reported_cost_usd.known_subtotal is None
    assert report.measured_account_spend is None


def test_token_subtotals_keep_integer_precision() -> None:
    count = 2**60 + 1
    coverage = usage_report([record(Usage(input_tokens=count))]).groups[0].fields["input_tokens"]
    assert coverage.known_subtotal == count
    assert isinstance(coverage.known_subtotal, int)


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "cost_usd"])
def test_limits_initial_unknown_coverage_and_thresholds(field: str) -> None:
    budget = Budgets.model_validate({"reported_" + field: 10})
    assert budget_stop_reason([], budget) is None
    assert "unknown" in (budget_stop_reason([record()], budget) or "")
    usage = Usage.model_validate({field: 10, "cost_source": "reported"})
    assert "threshold" in (budget_stop_reason([record(usage)], budget) or "")
    setattr(usage, field, 9)
    assert budget_stop_reason([record(usage)], budget) is None


def test_client_estimate_cannot_satisfy_reported_cost_budget() -> None:
    usage = Usage(cost_usd=1, cost_source="client_estimate")
    assert "unknown" in (budget_stop_reason([record(usage)], Budgets(reported_cost_usd=5)) or "")


@pytest.mark.parametrize(
    ("amounts", "limit"),
    [([0.3, 0.3, 0.3], 0.9), ([0.1, 0.2], 0.3), ([0.1] * 10, 1.0)],
)
def test_decimal_reported_cost_threshold_and_subtotal(amounts: list[float], limit: float) -> None:
    rows = [record(Usage(cost_usd=amount, cost_source="reported")) for amount in amounts]
    assert "threshold" in (budget_stop_reason(rows, Budgets(reported_cost_usd=limit)) or "")
    assert usage_report(rows).groups[0].reported_cost_usd.known_subtotal == limit


@pytest.mark.parametrize("limit", [0.9000000000000001, 0.91])
def test_decimal_reported_cost_below_threshold_still_allows_call(limit: float) -> None:
    rows = [record(Usage(cost_usd=0.3, cost_source="reported")) for _ in range(3)]
    assert budget_stop_reason(rows, Budgets(reported_cost_usd=limit)) is None


def test_native_cache_and_reasoning_are_not_added_to_token_limits() -> None:
    usage = Usage(
        input_tokens=2,
        output_tokens=1,
        cached_input_tokens=999,
        reasoning_tokens=999,
        cache_creation_input_tokens=999,
    )
    assert budget_stop_reason([record(usage)], Budgets(reported_input_tokens=3)) is None


def pricing(semantics: str = "inclusive") -> PricingRule:
    return PricingRule.model_validate(
        {
            "provider": "fake",
            "model": "model",
            "version": "2026-10-26",
            "label": "user table",
            "input_semantics": semantics,
            "input_per_million": 10,
            "output_per_million": 20,
            "cached_input_per_million": 1,
            "cache_creation_per_million": 12,
        }
    )


def test_explicit_pricing_semantics_and_unknowns() -> None:
    usage = Usage(
        input_tokens=100, output_tokens=10, cached_input_tokens=20, cache_creation_input_tokens=10
    )
    assert estimate_cost(usage, pricing()) == pytest.approx(0.00104)
    assert estimate_cost(usage, pricing("exclusive")) == pytest.approx(0.00134)
    usage.cached_input_tokens = None
    assert estimate_cost(usage, pricing()) is None
    assert usage_report([record(usage)], [pricing()]).groups[0].pricing_estimate_usd.missing == 1
    usage.cached_input_tokens = 101
    assert estimate_cost(usage, pricing()) is None


def test_invalid_pricing_models_and_nonfinite_costs_rejected() -> None:
    with pytest.raises(ValidationError):
        Usage(cost_usd=float("nan"))
    with pytest.raises(ValidationError):
        Budgets(reported_cost_usd=float("inf"))
    with pytest.raises(ValidationError):
        ProjectConfig(pricing=[pricing(), pricing()])
    with pytest.raises(ValidationError):
        ProjectConfig(role_models={Role.ENGINEER: " "})
    with pytest.raises(ValidationError):
        TaskSpec(description="Fix", acceptance=["pass"], model=" ")


def test_store_joins_resumed_executions_and_preserves_reserved_selection(repo: Path) -> None:
    store = Store(repo)
    task = Task(
        project=repo,
        config=ProjectConfig(),
        spec=TaskSpec(description="Fix answer", acceptance=["pass"]),
    )
    store.create(task)
    for model, finished in [("first", True), (None, False)]:
        task.execution_id = identity()
        store.start_execution(task)
        task.pending_role = Role.PLANNER
        task.pending_model = model
        task.pending_invocation_id = identity()
        store.begin_invocation(task)
        if finished:
            store.invocation(
                task,
                ProviderResult(status="success", usage=Usage(input_tokens=7)).model_dump_json(),
                invocation_id=task.pending_invocation_id,
            )
        store.finish_execution(task)
    rows = store.invocations(task.id)
    assert len(rows) == 2 and rows[0].model == "first" and rows[1].model is None
    assert rows[0].role == Role.PLANNER and rows[1].status == "started"
    assert rows[0].result is not None and rows[0].result.usage.input_tokens == 7
    assert rows[1].result is None
    store.invocation(task, '{"usage":{"input_tokens":9}}', invocation_id=identity())
    legacy = store.invocations(task.id)[-1]
    assert legacy.status == "unknown" and legacy.result is not None
    assert legacy.result.usage.input_tokens == 9
    store.close()

"""Pure resource summaries. Native counters are never combined into billing tokens."""

from collections import Counter, defaultdict
from collections.abc import Sequence
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import Field

from eng.core.models import (
    Budgets,
    Contract,
    InvocationRecord,
    PricingRule,
    Role,
    State,
    Task,
    Usage,
    VerificationResult,
)

TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "cache_creation_input_tokens",
    "reasoning_tokens",
)


class Coverage(Contract):
    known_subtotal: int | float | None = None
    reported: int = 0
    missing: int = 0


class UsageGroup(Contract):
    provider: str
    model: str | None
    role: Role
    invocations: int
    fields: dict[str, Coverage]
    reported_cost_usd: Coverage
    client_estimate_cost_usd: Coverage
    pricing_estimate_usd: Coverage
    pricing_version: str | None = None
    pricing_label: str | None = None
    actual_models: list[str] = Field(default_factory=list)
    actual_model_missing: int = 0
    outcomes: dict[str, int] = Field(default_factory=dict)
    packet_chars: Coverage = Field(default_factory=Coverage)
    packet_utf8_bytes: Coverage = Field(default_factory=Coverage)
    context_duration_seconds: Coverage = Field(default_factory=Coverage)
    role_duration_seconds: Coverage = Field(default_factory=Coverage)
    provider_duration_seconds: Coverage = Field(default_factory=Coverage)
    provider_executions: Coverage = Field(default_factory=Coverage)


class TaskUsageOutcome(Contract):
    task_id: str
    state: State
    active_wall_seconds: float
    repair_attempts: int
    completed_repair_handoffs: int
    # Deterministic completion is not human acceptance or proof of fixed defects.
    human_acceptance: None = None
    repaired_defects: None = None
    required_check_outcomes: dict[str, int] = Field(default_factory=dict)
    review_passed: bool
    verified_digest: str | None
    review_digest: str | None
    invocations: int = 0
    fields: dict[str, Coverage] = Field(default_factory=dict)


class UsageReport(Contract):
    schema_version: Literal[2] = 2
    invocations: int
    groups: list[UsageGroup] = Field(default_factory=list)
    totals: dict[str, Coverage] = Field(default_factory=dict)
    outcomes: dict[str, int] = Field(default_factory=dict)
    tasks: list[TaskUsageOutcome] = Field(default_factory=list)
    check_outcomes: dict[str, int] = Field(default_factory=dict)
    check_duration_seconds: float | None = None
    checks_scope: Literal["unavailable", "latest_task_results", "supplied_history"] = "unavailable"
    missing_telemetry: list[str] = Field(default_factory=list)
    measurement_sources: dict[str, str] = Field(
        default_factory=lambda: {
            "orchestration_invocations": "measured",
            "provider_executions": "measured",
            "packet_chars": "measured",
            "packet_utf8_bytes": "measured",
            "context_duration_seconds": "measured",
            "role_duration_seconds": "measured",
            "provider_duration_seconds": "measured",
            "native_token_counters": "provider_reported",
            "actual_model": "provider_reported_when_explicit",
            "selected_model": "operator_configuration",
            "reported_cost_usd": "provider_reported",
            "client_estimate_cost_usd": "client_estimated",
            "pricing_estimate_usd": "user_pricing_estimated",
            "internal_model_turns": "unavailable",
            "internal_tool_turns": "unavailable",
            "provider_cli_sessions": "unavailable",
            "subscription_allowance": "unavailable",
            "human_acceptance": "unavailable",
            "repaired_defects": "unavailable",
            "measured_account_spend": "unavailable",
        }
    )
    measured_account_spend: None = None
    subscription_allowance: None = None
    provider_cli_sessions: None = None
    internal_model_turns: None = None
    internal_tool_turns: None = None
    limit_semantics: str = (
        "Per-field native reported counters across all executions; cache/reasoning counters "
        "are not added to input/output. Limits stop new calls and cannot cap in-flight usage."
    )


def _usage(record: InvocationRecord) -> Usage:
    return Usage() if record.result is None else record.result.usage


def decimal_cost_total(values: Sequence[float]) -> Decimal:
    """Sum decimal spellings without introducing binary floating point drift."""
    # Finite binary64 spellings span at most 633 decimal places. This also
    # preserves small contributions when the amounts have widely different scales.
    with localcontext() as context:
        context.prec = 700
        return sum((Decimal(str(value)) for value in values), Decimal(0))


def _coverage(values: Sequence[int | float | None], *, monetary: bool = False) -> Coverage:
    known = [value for value in values if value is not None]
    subtotal = (
        float(decimal_cost_total([float(value) for value in known])) if monetary else sum(known)
    )
    return Coverage(
        known_subtotal=subtotal if known else None,
        reported=len(known),
        missing=len(values) - len(known),
    )


def estimate_cost(usage: Usage, rule: PricingRule) -> float | None:
    """Price only known native counters under explicitly declared input semantics.

    An absent cache rate means this rule does not separately price that counter.
    For inclusive input it remains charged at the input rate; for exclusive input
    the counter must be known zero, otherwise the estimate is incomplete.
    """
    if usage.input_tokens is None or usage.output_tokens is None:
        return None
    base = usage.input_tokens
    cost = usage.output_tokens * rule.output_per_million
    for count, rate in (
        (usage.cached_input_tokens, rule.cached_input_per_million),
        (usage.cache_creation_input_tokens, rule.cache_creation_per_million),
    ):
        if rate is None:
            if rule.input_semantics == "exclusive" and count != 0:
                return None
            continue
        if count is None:
            return None
        if rule.input_semantics == "inclusive":
            base -= count
        cost += count * rate
    if base < 0:
        return None  # Counters do not fit the user's chosen semantics.
    return (cost + base * rule.input_per_million) / 1_000_000


def usage_report(
    records: Sequence[InvocationRecord],
    pricing: Sequence[PricingRule] = (),
    *,
    tasks: Sequence[Task] = (),
    checks: Sequence[VerificationResult] | None = None,
) -> UsageReport:
    grouped: dict[tuple[str, str | None, Role], list[InvocationRecord]] = defaultdict(list)
    rules = {(rule.provider, rule.model): rule for rule in pricing}
    for record in records:
        grouped[(record.provider, record.model, record.role)].append(record)
    groups = []
    for (provider, model, role), entries in grouped.items():
        usages = [_usage(entry) for entry in entries]
        rule = rules.get((provider, model)) if model is not None else None
        groups.append(
            UsageGroup(
                provider=provider,
                model=model,
                role=role,
                invocations=len(entries),
                fields={
                    name: _coverage([getattr(usage, name) for usage in usages])
                    for name in TOKEN_FIELDS
                },
                reported_cost_usd=_coverage(
                    [
                        usage.cost_usd if usage.cost_source == "reported" else None
                        for usage in usages
                    ],
                    monetary=True,
                ),
                client_estimate_cost_usd=_coverage(
                    [
                        usage.cost_usd if usage.cost_source == "client_estimate" else None
                        for usage in usages
                    ],
                    monetary=True,
                ),
                pricing_estimate_usd=_coverage(
                    [estimate_cost(usage, rule) if rule else None for usage in usages],
                    monetary=True,
                ),
                pricing_version=rule.version if rule else None,
                pricing_label=rule.label if rule else None,
                actual_models=sorted(
                    {
                        entry.result.actual_model
                        for entry in entries
                        if entry.result is not None and entry.result.actual_model is not None
                    }
                ),
                actual_model_missing=sum(
                    entry.result is None or entry.result.actual_model is None for entry in entries
                ),
                outcomes=dict(Counter(entry.status for entry in entries)),
                **_invocation_metrics(entries),
            )
        )
    totals = {
        name: _coverage([getattr(_usage(record), name) for record in records])
        for name in TOKEN_FIELDS
    }
    totals.update(_invocation_metrics(records))
    for cost_field in ("reported_cost_usd", "client_estimate_cost_usd", "pricing_estimate_usd"):
        coverages = [getattr(group, cost_field) for group in groups]
        totals[cost_field] = Coverage(
            known_subtotal=(
                float(
                    decimal_cost_total(
                        [
                            float(item.known_subtotal)
                            for item in coverages
                            if item.known_subtotal is not None
                        ]
                    )
                )
                if any(item.reported for item in coverages)
                else None
            ),
            reported=sum(item.reported for item in coverages),
            missing=sum(item.missing for item in coverages),
        )
    observed_checks = (
        list(checks)
        if checks is not None
        else [result for task in tasks for result in task.verification]
    )
    missing = [name for name, coverage in totals.items() if coverage.missing]
    if any(group.actual_model_missing for group in groups):
        missing.append("actual_model")
    if any(record.task_id is None for record in records):
        missing.append("task_attribution")
    missing.extend(
        [
            "internal_model_turns",
            "internal_tool_turns",
            "provider_cli_sessions",
            "subscription_allowance",
            "measured_account_spend",
            "human_acceptance",
            "repaired_defects",
        ]
    )
    if checks is None:
        missing.append("historical_check_results")
    return UsageReport(
        invocations=len(records),
        groups=groups,
        totals=totals,
        outcomes=dict(Counter(record.status for record in records)),
        tasks=[
            TaskUsageOutcome(
                task_id=task.id,
                state=task.state,
                active_wall_seconds=task.elapsed_seconds,
                repair_attempts=len(task.repairs),
                completed_repair_handoffs=sum(
                    attempt.handoff is not None for attempt in task.repairs
                ),
                required_check_outcomes=dict(
                    Counter(result.outcome for result in task.verification if result.required)
                ),
                review_passed=task.review_passed,
                verified_digest=task.verified_digest,
                review_digest=task.review_digest,
                invocations=sum(record.task_id == task.id for record in records),
                fields={
                    name: _coverage(
                        [
                            getattr(_usage(record), name)
                            for record in records
                            if record.task_id == task.id
                        ]
                    )
                    for name in TOKEN_FIELDS
                },
            )
            for task in tasks
        ],
        check_outcomes=dict(Counter(result.outcome for result in observed_checks)),
        check_duration_seconds=(
            sum(result.duration_seconds for result in observed_checks) if observed_checks else None
        ),
        checks_scope=(
            "supplied_history"
            if checks is not None
            else "latest_task_results"
            if tasks
            else "unavailable"
        ),
        missing_telemetry=missing,
    )


def _invocation_metrics(records: Sequence[InvocationRecord]) -> dict[str, Coverage]:
    metrics = {}
    for name in (
        "packet_chars",
        "packet_utf8_bytes",
        "context_duration_seconds",
        "role_duration_seconds",
        "provider_executions",
    ):
        values: list[int | float | None] = []
        for record in records:
            telemetry = record.result.telemetry if record.result else None
            values.append(
                None
                if telemetry is None
                else int(telemetry.provider_invoked)
                if name == "provider_executions"
                else getattr(telemetry, name)
            )
        metrics[name] = _coverage(values)
    # Default 0 on old results cannot prove a timing measurement was collected.
    metrics["provider_duration_seconds"] = _coverage(
        [
            record.result.duration_seconds
            if record.result is not None
            and record.result.telemetry is not None
            and record.result.telemetry.provider_invoked
            and record.result.duration_seconds > 0
            else None
            for record in records
        ]
    )
    return metrics


def budget_stop_reason(records: Sequence[InvocationRecord], budgets: Budgets) -> str | None:
    """Stop before a new call; empty history allows the initial invocation."""
    if not records:
        return None
    usages = [_usage(record) for record in records]
    for field in ("input_tokens", "output_tokens", "cost_usd"):
        limit = getattr(budgets, "reported_" + field)
        if limit is None:
            continue
        values = [
            getattr(usage, field)
            if field != "cost_usd" or usage.cost_source == "reported"
            else None
            for usage in usages
        ]
        coverage = _coverage(values)
        if coverage.missing:
            return f"Reported {field} coverage unknown; inspect usage before further model work"
        reached = (
            decimal_cost_total([float(value) for value in values if value is not None])
            >= Decimal(str(limit))
            if field == "cost_usd"
            else coverage.known_subtotal is not None and coverage.known_subtotal >= limit
        )
        if reached:
            return f"Reported {field} stop threshold reached; extend explicitly"
    return None

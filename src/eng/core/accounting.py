"""Pure resource summaries. Native counters are never combined into billing tokens."""

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal, localcontext

from pydantic import Field

from eng.core.models import Budgets, Contract, InvocationRecord, PricingRule, Role, Usage

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


class UsageReport(Contract):
    invocations: int
    groups: list[UsageGroup] = Field(default_factory=list)
    measured_account_spend: None = None
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
    records: Sequence[InvocationRecord], pricing: Sequence[PricingRule] = ()
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
            )
        )
    return UsageReport(invocations=len(records), groups=groups)


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

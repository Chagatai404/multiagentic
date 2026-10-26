"""Pure E3 routing: explicit operator rules select a provider or model by classification.

Rules come only from project/user configuration; no rule is inferred from usage, and no
route changes the workflow (planner, review, approval, checks, repairs). Explicit task,
node and plan selections always win. Model routes are evaluated per invocation with the
current classification, so changed-path escalation selects the matching stronger route.
Provider routes are evaluated once, when a task or plan node is created.
"""

from collections.abc import Sequence

from pydantic import Field

from eng.core.models import (
    Classification,
    ClassificationOverrides,
    Contract,
    Role,
    RouteRule,
    TaskSpec,
)
from eng.core.plan import PlanNodeSpec, node_description
from eng.core.workflow import classify_task


class RouteDecision(Contract):
    label: str
    index: int = Field(ge=0)
    provider: str | None = None
    model: str | None = None


def _matches(rule: RouteRule, classification: Classification, role: Role | None) -> bool:
    when = rule.when
    return (
        (not when.task_types or classification.task_type in when.task_types)
        and (not when.complexities or classification.complexity in when.complexities)
        and (not when.risks or classification.risk in when.risks)
        and (not when.roles or (role is not None and role in when.roles))
    )


def route_model(
    rules: Sequence[RouteRule], classification: Classification, role: Role
) -> RouteDecision | None:
    """First matching rule that names a model, for this role and classification."""
    for index, rule in enumerate(rules):
        if rule.model is not None and _matches(rule, classification, role):
            return RouteDecision(label=rule.label, index=index, model=rule.model)
    return None


def route_provider(
    rules: Sequence[RouteRule], classification: Classification
) -> RouteDecision | None:
    """First matching rule that names a provider; evaluated at task creation."""
    for index, rule in enumerate(rules):
        if rule.provider is not None and _matches(rule, classification, None):
            return RouteDecision(label=rule.label, index=index, provider=rule.provider)
    return None


def select_provider(
    explicit: str | None,
    rules: Sequence[RouteRule],
    classification: Classification,
    default: str,
) -> tuple[str, RouteDecision | None]:
    """Explicit selection, else the first matching provider route, else the default."""
    if explicit is not None:
        return explicit, None
    decision = route_provider(rules, classification)
    if decision is None or decision.provider is None:
        return default, None
    return decision.provider, decision


def node_classification(spec: PlanNodeSpec) -> Classification:
    """The initial classification a plan node's task will receive (no changed paths)."""
    return classify_task(
        TaskSpec(
            description=node_description(spec),
            acceptance=spec.acceptance,
            context_paths=spec.context_paths,
            classification_overrides=ClassificationOverrides(risk=spec.risk),
        )
    )

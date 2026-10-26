import pytest
from pydantic import ValidationError

from eng.core.models import (
    Classification,
    Complexity,
    ProjectConfig,
    Risk,
    Role,
    RouteRule,
    TaskType,
)
from eng.core.plan import PlanNodeSpec
from eng.core.routing import node_classification, route_model, route_provider, select_provider


def rule(label: str, **values: object) -> RouteRule:
    return RouteRule.model_validate({"label": label, **values})


def classified(complexity: Complexity = Complexity.SMALL, risk: Risk = Risk.LOW) -> Classification:
    return Classification(task_type=TaskType.CHANGE, complexity=complexity, risk=risk)


RULES = [
    rule("review-risky", when={"risks": ["medium", "high"], "roles": ["reviewer"]}, model="strong"),
    rule("cheap-small", when={"complexities": ["small"]}, model="mini"),
    rule("complex-provider", when={"complexities": ["complex"]}, provider="claude"),
    rule("fallback", model="standard"),
]


def test_model_routes_use_first_match_on_role_and_current_classification() -> None:
    small = classified()

    def label(classification: Classification, role: Role) -> tuple[str, str | None] | None:
        decision = route_model(RULES, classification, role)
        return None if decision is None else (decision.label, decision.model)

    assert label(small, Role.ENGINEER) == ("cheap-small", "mini")
    # A reviewer on low-risk small work falls through the role-specific rule.
    assert label(small, Role.REVIEWER) == ("cheap-small", "mini")
    assert label(classified(risk=Risk.MEDIUM), Role.REVIEWER) == ("review-risky", "strong")
    # Provider-only rules never select a model.
    assert label(classified(Complexity.COMPLEX), Role.PLANNER) == ("fallback", "standard")
    assert route_model([], small, Role.ENGINEER) is None


def test_provider_routes_ignore_model_rules_and_explicit_selection_wins() -> None:
    complex_work = classified(Complexity.COMPLEX)
    assert route_provider(RULES, classified()) is None
    decision = route_provider(RULES, complex_work)
    assert decision is not None and decision.provider == "claude"
    assert select_provider("codex", RULES, complex_work, "fake") == ("codex", None)
    name, decision = select_provider(None, RULES, complex_work, "fake")
    assert name == "claude" and decision is not None and decision.label == "complex-provider"
    assert select_provider(None, RULES, classified(), "fake") == ("fake", None)


@pytest.mark.parametrize(
    "values",
    [
        {"label": "empty"},
        {"label": "blank", "model": " "},
        {"label": "role-provider", "provider": "codex", "when": {"roles": ["engineer"]}},
        {"label": "verifier", "model": "m", "when": {"roles": ["verifier"]}},
        {"label": "bad label!", "model": "m"},
        {"label": "bad-provider", "provider": "Not A Name"},
        {"label": "extra", "model": "m", "unknown": 1},
    ],
)
def test_invalid_rules_are_rejected(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RouteRule.model_validate(values)


def test_project_config_bounds_and_requires_unique_labels() -> None:
    assert ProjectConfig(routing=RULES).routing == RULES
    with pytest.raises(ValidationError, match="unique"):
        ProjectConfig(routing=[rule("a", model="x"), rule("a", model="y")])
    with pytest.raises(ValidationError):
        ProjectConfig(routing=[rule(f"r{index}", model="x") for index in range(51)])
    assert ProjectConfig().routing == []


def test_node_classification_matches_the_task_a_node_will_create() -> None:
    node = PlanNodeSpec(
        id="n", description="Redesign the architecture", acceptance=["ok"], owns=["src/**"]
    )
    assert node_classification(node).complexity == Complexity.COMPLEX
    risky = node.model_copy(update={"risk": Risk.HIGH})
    assert node_classification(risky).risk == Risk.HIGH

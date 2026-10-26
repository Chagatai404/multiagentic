from eng.core.models import (
    Budgets,
    Classification,
    Complexity,
    Preset,
    ProjectConfig,
    Risk,
    Role,
    RoleLimits,
    TaskType,
    WorkflowPolicy,
)
from eng.core.plan import PlanSpec
from eng.core.presets import PROFILES, apply_preset, node_allocation, required_calls


def classified(
    complexity: Complexity = Complexity.SMALL,
    risk: Risk = Risk.LOW,
    task_type: TaskType = TaskType.CHANGE,
) -> Classification:
    return Classification(task_type=task_type, complexity=complexity, risk=risk)


def test_required_calls_follow_the_existing_workflow_decision() -> None:
    policy = WorkflowPolicy()
    assert required_calls(classified(), policy) == 1
    assert required_calls(classified(risk=Risk.MEDIUM), policy) == 2
    assert required_calls(classified(Complexity.COMPLEX), policy) == 3
    assert required_calls(classified(task_type=TaskType.QUESTION), policy) == 0


def test_presets_budget_required_roles_plus_their_repairs() -> None:
    base = Budgets(
        model_calls=9,
        reported_cost_usd=1.5,
        role_limits={Role.REVIEWER: RoleLimits(model_calls=2)},
    )
    policy = WorkflowPolicy()
    cases = {
        (Preset.ECONOMY, Complexity.SMALL): 1,
        (Preset.ECONOMY, Complexity.COMPLEX): 3,
        (Preset.BALANCED, Complexity.SMALL): 2,
        (Preset.BALANCED, Complexity.COMPLEX): 5,  # planner, engineer, review + repair+review
        (Preset.RIGOROUS, Complexity.COMPLEX): 7,
    }
    for (preset, complexity), calls in cases.items():
        budgets, workflow = apply_preset(preset, base, policy, classified(complexity))
        profile = PROFILES[preset]
        assert budgets.model_calls == calls, (preset, complexity)
        assert budgets.context_chars == profile.context_chars
        assert workflow.max_repairs == profile.max_repairs
        assert workflow.repair_headroom == profile.repair_headroom
        assert workflow.stop_unchanged_repairs == profile.stop_unchanged_repairs
        # Thresholds and role sublimits are untouched; inputs are not mutated.
        assert budgets.reported_cost_usd == 1.5 and budgets.role_limits == base.role_limits
    assert base.model_calls == 9 and policy == WorkflowPolicy()


def test_economy_and_balanced_enable_e4_rigorous_keeps_the_previous_loop() -> None:
    assert PROFILES[Preset.ECONOMY].repair_headroom and PROFILES[Preset.BALANCED].repair_headroom
    rigorous = PROFILES[Preset.RIGOROUS]
    assert not rigorous.repair_headroom and not rigorous.stop_unchanged_repairs


def plan(**extra: object) -> PlanSpec:
    return PlanSpec.model_validate(
        {
            "name": "p",
            "nodes": [
                {
                    "id": "a",
                    "description": "Redesign the architecture",
                    "acceptance": ["ok"],
                    "owns": ["a/**"],
                },
                {
                    "id": "b",
                    "description": "Fix b",
                    "acceptance": ["ok"],
                    "owns": ["b/**"],
                    "budgets": {"model_calls": 4},
                    "max_repairs": 3,
                },
            ],
            **extra,
        }
    )


def test_node_allocation_puts_presets_beneath_plan_and_node_settings() -> None:
    config = ProjectConfig()
    spec = plan(preset="balanced", node_budgets={"context_chars": 9000})
    budgets, repairs, workflow = node_allocation(config, spec, spec.nodes[0])
    assert (budgets.model_calls, budgets.context_chars, repairs) == (5, 9000, 1)
    assert workflow.repair_headroom and workflow.max_repairs == 1
    budgets, repairs, workflow = node_allocation(config, spec, spec.nodes[1])
    assert (budgets.model_calls, repairs, workflow.max_repairs) == (4, 3, 3)
    # Without a preset the allocation is the E1 resolution of project settings.
    budgets, repairs, workflow = node_allocation(config, plan(), plan().nodes[0])
    assert budgets == config.budgets and repairs == config.workflow.max_repairs
    assert workflow == config.workflow

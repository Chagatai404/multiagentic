"""Pure E5 operating presets: named, explicit bundles of existing settings.

A preset is operator shorthand, not a claim of optimality: no live measurement backs
any of these values. It sets the repair ceiling, the E4 repair economies and the packet
cap, and derives the model-call allowance from the roles the task's classification
already requires, so it can never under-budget planning or review. It never changes
classification, risk, required roles, approval, checks, ownership or reported-usage
thresholds. Explicit task/plan/node settings override it.
"""

from pydantic import Field

from eng.core.models import (
    Budgets,
    Classification,
    Contract,
    Preset,
    ProjectConfig,
    TaskType,
    WorkflowPolicy,
)
from eng.core.plan import PlanNodeSpec, PlanSpec, resolve_budgets
from eng.core.routing import node_classification
from eng.core.workflow import select_workflow


class PresetProfile(Contract):
    max_repairs: int = Field(ge=0, le=10)
    repair_headroom: bool
    stop_unchanged_repairs: bool
    context_chars: int = Field(ge=256, le=1000000)


PROFILES: dict[Preset, PresetProfile] = {
    Preset.ECONOMY: PresetProfile(
        max_repairs=0, repair_headroom=True, stop_unchanged_repairs=True, context_chars=12000
    ),
    Preset.BALANCED: PresetProfile(
        max_repairs=1, repair_headroom=True, stop_unchanged_repairs=True, context_chars=16000
    ),
    # The pre-E4 loop: no early repair stops, more repairs and a larger packet.
    Preset.RIGOROUS: PresetProfile(
        max_repairs=2, repair_headroom=False, stop_unchanged_repairs=False, context_chars=24000
    ),
}


def required_calls(classification: Classification, policy: WorkflowPolicy) -> int:
    """Model calls for the initial required roles; questions make none."""
    if classification.task_type == TaskType.QUESTION:
        return 0
    decision = select_workflow(classification, policy)
    return int(decision.planner) + 1 + int(decision.reviewer)


def apply_preset(
    preset: Preset,
    budgets: Budgets,
    policy: WorkflowPolicy,
    classification: Classification,
) -> tuple[Budgets, WorkflowPolicy]:
    """Return new budgets/workflow with the preset applied; inputs are not mutated."""
    profile = PROFILES[preset]
    workflow = policy.model_copy(
        update={
            "max_repairs": profile.max_repairs,
            "repair_headroom": profile.repair_headroom,
            "stop_unchanged_repairs": profile.stop_unchanged_repairs,
        }
    )
    reviewer = select_workflow(classification, workflow).reviewer
    calls = required_calls(classification, workflow) + profile.max_repairs * (1 + int(reviewer))
    resolved = budgets.model_copy(
        deep=True,
        update={"model_calls": min(100, max(1, calls)), "context_chars": profile.context_chars},
    )
    return Budgets.model_validate(resolved.model_dump()), workflow


def node_allocation(
    config: ProjectConfig, spec: PlanSpec, node: PlanNodeSpec
) -> tuple[Budgets, int, WorkflowPolicy]:
    """Effective budgets, repair ceiling and workflow for one plan node.

    Precedence: project config → plan preset → plan `node_budgets` / `node_max_repairs`
    → node `budgets` / `max_repairs`.
    """
    budgets, workflow = config.budgets, config.workflow
    if spec.preset is not None:
        budgets, workflow = apply_preset(spec.preset, budgets, workflow, node_classification(node))
    resolved = resolve_budgets(budgets, spec.node_budgets, node.budgets)
    max_repairs = (
        node.max_repairs
        if node.max_repairs is not None
        else spec.node_max_repairs
        if spec.node_max_repairs is not None
        else workflow.max_repairs
    )
    return resolved, max_repairs, workflow.model_copy(update={"max_repairs": max_repairs})

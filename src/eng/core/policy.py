"""Pure policy: no filesystem, providers, database, or subprocess imports."""

from eng.core.models import State, VerificationResult

TERMINAL = frozenset({State.COMPLETED, State.FAILED, State.CANCELLED})
FLOW: dict[State, set[State]] = {
    State.CREATED: {State.CLASSIFYING},
    State.CLASSIFYING: {State.PREPARING_CONTEXT, State.BLOCKED},
    State.PREPARING_CONTEXT: {
        State.IMPLEMENTING,
        State.PLANNING,
        State.VERIFYING,
        State.REVIEWING,
        State.DEBUGGING,
    },
    State.PLANNING: {State.IMPLEMENTING, State.BLOCKED},
    State.IMPLEMENTING: {State.VERIFYING},
    State.VERIFYING: {
        State.COMPLETED,
        State.REVIEWING,
        State.DEBUGGING,
        State.BLOCKED,
        State.PLANNING,
    },
    State.REVIEWING: {State.COMPLETED, State.DEBUGGING, State.BLOCKED},
    State.DEBUGGING: {State.VERIFYING},
    State.PAUSED: {
        State.CLASSIFYING,
        State.PREPARING_CONTEXT,
        State.PLANNING,
        State.IMPLEMENTING,
        State.VERIFYING,
        State.REVIEWING,
        State.DEBUGGING,
        State.BLOCKED,
    },
    State.BLOCKED: {
        State.CLASSIFYING,
        State.PREPARING_CONTEXT,
        State.PLANNING,
        State.IMPLEMENTING,
        State.VERIFYING,
        State.REVIEWING,
        State.DEBUGGING,
    },
}


def validate_transition(old: State, new: State) -> None:
    allowed = FLOW.get(old, set())
    if old not in TERMINAL:
        allowed = allowed | {State.PAUSED, State.FAILED, State.CANCELLED}
    if new not in allowed:
        raise ValueError(f"Illegal task transition: {old} -> {new}")


def completion_gate(results: list[VerificationResult]) -> tuple[bool, str]:
    required = [result for result in results if result.required]
    if not required:
        return False, "No required verification checks configured"
    failed = [result.check_id for result in required if result.outcome != "PASS"]
    if failed:
        return False, "Required checks did not pass: " + ", ".join(failed)
    return True, "All required checks passed; human acceptance of the task remains external"

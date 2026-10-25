import pytest
from pydantic import ValidationError

from eng.core.models import Check, State, TaskSpec, Usage, VerificationResult
from eng.core.policy import TERMINAL, completion_gate, validate_transition


@pytest.mark.parametrize("state", list(TERMINAL))
def test_terminal_states_cannot_be_reopened(state: State) -> None:
    for target in State:
        with pytest.raises(ValueError, match="Illegal"):
            validate_transition(state, target)


def test_state_machine_rejects_shortcut_to_completed() -> None:
    with pytest.raises(ValueError):
        validate_transition(State.IMPLEMENTING, State.COMPLETED)


@pytest.mark.parametrize("outcome", ["FAIL", "SKIPPED", "UNAVAILABLE", "ERROR"])
def test_required_nonpass_blocks_completion(outcome: str) -> None:
    result = VerificationResult(
        check_id="tests", command=["check"], environment="fixture", outcome=outcome
    )  # type: ignore[arg-type]
    assert not completion_gate([result])[0]


def test_gate_requires_required_check_and_allows_optional_failures() -> None:
    assert not completion_gate([])[0]
    optional = VerificationResult(
        check_id="optional",
        command=["check"],
        environment="fixture",
        outcome="FAIL",
        required=False,
    )
    assert not completion_gate([optional])[0]
    required = optional.model_copy(update={"required": True, "outcome": "PASS"})
    assert completion_gate([required, optional])[0]


def test_contracts_reject_unknown_and_invalid_values() -> None:
    with pytest.raises(ValidationError):
        TaskSpec(description=" ", acceptance=["works"])
    with pytest.raises(ValidationError):
        TaskSpec(description="fix", acceptance=[" "])
    with pytest.raises(ValidationError):
        Check(name="../escape", argv=["python"])
    with pytest.raises(ValidationError):
        Check(name="valid", argv=[""])
    with pytest.raises(ValidationError):
        Usage(input_tokens=-1)
    with pytest.raises(ValidationError):
        TaskSpec(description="fix", acceptance=["works"], unexpected=True)  # type: ignore[call-arg]
    assert Usage().cost_usd is None

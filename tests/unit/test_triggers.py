import pytest

from eng.core.triggers import (
    TriggerAction,
    TriggerEnvelope,
    TriggerMode,
    TriggerOrigin,
    idempotency_key,
    prompt_digest,
    route_trigger,
)


def envelope(
    prompt: str, *, turn_id: str | None = None, session_id: str | None = "s1"
) -> TriggerEnvelope:
    return TriggerEnvelope(
        origin=TriggerOrigin.CLAUDE_CODE,
        session_id=session_id,
        turn_id=turn_id,
        cwd="D:/work",
        prompt=prompt,
        received_at="2026-10-26T00:00:00+00:00",
    )


def test_prompt_digest_normalizes_whitespace_and_case() -> None:
    assert prompt_digest("  Fix   the\tParser\n") == prompt_digest("fix the parser")
    assert prompt_digest("fix the parser") != prompt_digest("fix the lexer")


def test_turn_id_keys_differ_per_turn_and_mark_not_content_keyed() -> None:
    first, first_content = idempotency_key(envelope("fix it", turn_id="t1"))
    second, _ = idempotency_key(envelope("fix it", turn_id="t2"))
    assert first != second
    assert first_content is False


def test_content_keys_match_for_same_prompt_without_turn_id() -> None:
    first, first_content = idempotency_key(envelope("Fix  the parser"))
    second, second_content = idempotency_key(envelope("fix the parser"))
    other_session, _ = idempotency_key(envelope("fix the parser", session_id="s2"))
    assert first == second
    assert first_content is True and second_content is True
    assert first != other_session


def test_reentrant_beats_explicit_prefix() -> None:
    decision = route_trigger(envelope("eng: fix it"), TriggerMode.MANUAL, reentrant=True)
    assert decision.action == TriggerAction.REENTRANT
    assert decision.description is None


@pytest.mark.parametrize(
    "prompt", ["eng: Fix the parser", "  ENG:   Fix the parser  ", "Eng:Fix the parser"]
)
def test_eng_prefix_routes_in_manual_mode_and_strips_marker(prompt: str) -> None:
    decision = route_trigger(envelope(prompt), TriggerMode.MANUAL, reentrant=False)
    assert decision.action == TriggerAction.ROUTE
    assert decision.description == "Fix the parser"
    assert decision.full_verification is False


def test_blank_eng_request_bypasses() -> None:
    decision = route_trigger(envelope("eng:   "), TriggerMode.ADAPTIVE, reentrant=False)
    assert decision.action == TriggerAction.BYPASS


def test_slash_commands_bypass_even_in_adaptive_mode() -> None:
    decision = route_trigger(
        envelope("/fix the parser test now"), TriggerMode.ADAPTIVE, reentrant=False
    )
    assert decision.action == TriggerAction.BYPASS


def test_manual_mode_bypasses_imperative_prose() -> None:
    decision = route_trigger(
        envelope("Fix the failing parser test"), TriggerMode.MANUAL, reentrant=False
    )
    assert decision.action == TriggerAction.BYPASS


def test_questions_bypass_in_adaptive_mode() -> None:
    decision = route_trigger(
        envelope("How do I fix the failing parser test?"), TriggerMode.ADAPTIVE, reentrant=False
    )
    assert decision.action == TriggerAction.BYPASS


def test_imperative_change_routes_in_adaptive_mode() -> None:
    decision = route_trigger(
        envelope("Fix the failing parser test"), TriggerMode.ADAPTIVE, reentrant=False
    )
    assert decision.action == TriggerAction.ROUTE
    assert decision.description == "Fix the failing parser test"
    assert decision.full_verification is False


def test_please_and_write_tests_phrases_route() -> None:
    please = route_trigger(
        envelope("Please add a retry to the client"), TriggerMode.ADAPTIVE, reentrant=False
    )
    tests = route_trigger(
        envelope("Write tests for the trigger router"), TriggerMode.ADAPTIVE, reentrant=False
    )
    assert please.action == TriggerAction.ROUTE
    assert tests.action == TriggerAction.ROUTE


@pytest.mark.parametrize("prompt", ["fix?", "fix it", "Fix this?", "looks good to me", "fixes"])
def test_short_ambiguous_or_non_imperative_prose_bypasses(prompt: str) -> None:
    decision = route_trigger(envelope(prompt), TriggerMode.ADAPTIVE, reentrant=False)
    assert decision.action == TriggerAction.BYPASS


def test_full_mode_sets_full_verification_on_routed_work() -> None:
    adaptive = route_trigger(
        envelope("Implement the retry policy"), TriggerMode.ADAPTIVE, reentrant=False
    )
    full = route_trigger(envelope("Implement the retry policy"), TriggerMode.FULL, reentrant=False)
    explicit = route_trigger(envelope("eng: refactor the store"), TriggerMode.FULL, reentrant=False)
    assert adaptive.full_verification is False
    assert full.action == TriggerAction.ROUTE and full.full_verification is True
    assert explicit.full_verification is True

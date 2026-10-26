import json
import sys
from pathlib import Path

import pytest

from eng.core.triggers import TriggerAction, TriggerDecision, TriggerOrigin
from eng.integrations.clients import (
    HOOK_MODULE,
    hook_command,
    parse_hook_input,
    render_decision,
    render_error,
)

NOW = "2026-10-26T10:00:00+00:00"


def test_cursor_normalizes_single_workspace_and_generation_identity(tmp_path: Path) -> None:
    payload = {
        "prompt": "Fix the parser with multiple agents",
        "workspace_roots": [str(tmp_path)],
        "conversation_id": "conversation",
        "generation_id": "generation",
        "hook_event_name": "beforeSubmitPrompt",
    }
    envelope = parse_hook_input(TriggerOrigin.CURSOR, json.dumps(payload), received_at=NOW)
    assert envelope.cwd == str(tmp_path)
    assert envelope.session_id == "conversation" and envelope.turn_id == "generation"
    payload["workspace_roots"] = [str(tmp_path), str(tmp_path / "other")]
    with pytest.raises(ValueError, match="exactly one"):
        parse_hook_input(TriggerOrigin.CURSOR, json.dumps(payload), received_at=NOW)


@pytest.mark.parametrize("origin", [TriggerOrigin.GEMINI, TriggerOrigin.CURSOR])
def test_new_client_decision_blocks_only_a_started_task(
    origin: TriggerOrigin, tmp_path: Path
) -> None:
    decision = TriggerDecision(action=TriggerAction.ROUTE, reason="keyword", task_id="task-1")
    code, output = render_decision(origin, decision, project=tmp_path)
    result = json.loads(output)
    assert code == 0
    if origin is TriggerOrigin.GEMINI:
        assert result["decision"] == "deny" and "task-1" in result["reason"]
    else:
        assert result["continue"] is False and "task-1" in result["user_message"]
    assert render_decision(
        origin, decision.model_copy(update={"task_id": None}), project=tmp_path
    ) == (0, "")


CLAUDE_PAYLOAD = {
    "session_id": "sess-1",
    "transcript_path": "C:/Users/x/.claude/projects/p/sess-1.jsonl",
    "cwd": "D:/Projects/app",
    "hook_event_name": "UserPromptSubmit",
    "prompt": "eng: fix the parser",
    "prompt_id": "prompt-42",
}

CODEX_PAYLOAD = {
    "session_id": "sess-2",
    "turn_id": "turn-7",
    "transcript_path": None,
    "cwd": "D:/Projects/app",
    "hook_event_name": "UserPromptSubmit",
    "model": "gpt-5",
    "prompt": "Please add a retry to the client",
}


def test_claude_payload_parses_prompt_id_as_turn_id() -> None:
    envelope = parse_hook_input(
        TriggerOrigin.CLAUDE_CODE, json.dumps(CLAUDE_PAYLOAD), received_at=NOW
    )
    assert envelope.origin is TriggerOrigin.CLAUDE_CODE
    assert envelope.session_id == "sess-1"
    assert envelope.turn_id == "prompt-42"
    assert envelope.cwd == "D:/Projects/app"
    assert envelope.prompt == "eng: fix the parser"
    assert envelope.event == "UserPromptSubmit"
    assert envelope.received_at == NOW


def test_codex_payload_parses_turn_id() -> None:
    envelope = parse_hook_input(TriggerOrigin.CODEX, json.dumps(CODEX_PAYLOAD), received_at=NOW)
    assert envelope.origin is TriggerOrigin.CODEX
    assert envelope.turn_id == "turn-7"
    assert envelope.prompt == "Please add a retry to the client"


def test_non_string_optional_ids_are_ignored() -> None:
    payload = {**CODEX_PAYLOAD, "turn_id": 5, "session_id": None}
    envelope = parse_hook_input(TriggerOrigin.CODEX, json.dumps(payload), received_at=NOW)
    assert envelope.turn_id is None
    assert envelope.session_id is None


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   \n",
        "not json",
        "[]",
        '"just a string"',
        json.dumps({"cwd": "D:/x"}),
        json.dumps({"cwd": "D:/x", "prompt": 5}),
        json.dumps({"cwd": "D:/x", "prompt": None}),
        json.dumps({"prompt": "fix it"}),
    ],
)
def test_invalid_hook_input_raises_value_error(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_hook_input(TriggerOrigin.CLAUDE_CODE, raw, received_at=NOW)


def test_route_decision_blocks_with_task_and_status_command(tmp_path: Path) -> None:
    decision = TriggerDecision(
        action=TriggerAction.ROUTE, reason="explicit", task_id="task-abc", description="fix"
    )
    code, out = render_decision(TriggerOrigin.CLAUDE_CODE, decision, project=tmp_path)
    assert code == 0
    body = json.loads(out)
    assert body["decision"] == "block"
    assert "task-abc" in body["reason"]
    assert f"eng status task-abc -p {tmp_path}" in body["reason"]
    assert len(body["reason"]) < 1000


def test_duplicate_decision_blocks_with_existing_task(tmp_path: Path) -> None:
    decision = TriggerDecision(action=TriggerAction.DUPLICATE, reason="dup", task_id="task-1")
    code, out = render_decision(TriggerOrigin.CODEX, decision, project=tmp_path)
    assert code == 0
    body = json.loads(out)
    assert body["decision"] == "block"
    assert "task-1" in body["reason"]


def test_long_reason_is_clamped_under_limit(tmp_path: Path) -> None:
    long_project = tmp_path / ("nested-" * 200)
    decision = TriggerDecision(action=TriggerAction.ROUTE, reason="x", task_id="task-1")
    code, out = render_decision(TriggerOrigin.CLAUDE_CODE, decision, project=long_project)
    assert code == 0
    assert len(json.loads(out)["reason"]) <= 1000


@pytest.mark.parametrize("action", [TriggerAction.BYPASS, TriggerAction.REENTRANT])
def test_pass_through_decisions_emit_nothing(tmp_path: Path, action: TriggerAction) -> None:
    decision = TriggerDecision(action=action, reason="no", task_id="task-1")
    assert render_decision(TriggerOrigin.CODEX, decision, project=tmp_path) == (0, "")


def test_route_without_task_id_passes_through(tmp_path: Path) -> None:
    decision = TriggerDecision(action=TriggerAction.ROUTE, reason="no task yet")
    assert render_decision(TriggerOrigin.CODEX, decision, project=tmp_path) == (0, "")


def test_render_error_warns_without_blocking() -> None:
    code, out = render_error(TriggerOrigin.CLAUDE_CODE, "store locked")
    assert code == 0
    body = json.loads(out)
    assert set(body) == {"systemMessage"}
    assert "store locked" in body["systemMessage"]


@pytest.mark.parametrize("client", ["claude-code", "codex"])
def test_hook_command_argv_carries_marker_mode_and_provider(client: str) -> None:
    argv = hook_command(client, mode="adaptive", provider="claude")
    assert argv == [
        sys.executable,
        "-m",
        HOOK_MODULE,
        client,
        "--mode",
        "adaptive",
        "--provider",
        "claude",
    ]


@pytest.mark.parametrize(
    ("client", "mode", "provider"),
    [
        ("cli", "manual", "claude"),
        ("claude-code", "bogus", "claude"),
        ("codex", "manual", "--dangerous"),
        ("codex", "manual", ""),
    ],
)
def test_hook_command_rejects_invalid_arguments(client: str, mode: str, provider: str) -> None:
    with pytest.raises(ValueError):
        hook_command(client, mode=mode, provider=provider)

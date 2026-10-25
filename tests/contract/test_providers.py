import asyncio
import json
from pathlib import Path

from eng.core.models import ProviderRequest
from eng.providers.base import Provider
from eng.providers.codex import CodexProvider, parse_events
from eng.providers.fake import FakeProvider


def test_fake_provider_real_file_contract(tmp_path: Path) -> None:
    provider: Provider = FakeProvider({"src/answer.txt": "42"})
    request = ProviderRequest(
        task_id="task",
        execution_id="execution",
        workspace=tmp_path,
        prompt="fixture edit",
        timeout_seconds=5,
    )
    result = asyncio.run(provider.execute(request, tmp_path / "artifacts", lambda: False))
    assert result.status == "success"
    assert (tmp_path / "src/answer.txt").read_text() == "42"
    assert result.usage.input_tokens is None
    assert not provider.capabilities.tool_execution
    cancelled = asyncio.run(provider.execute(request, tmp_path, lambda: True))
    assert cancelled.status == "cancelled"


def test_codex_jsonl_and_usage_contract() -> None:
    events = [
        {"type": "thread.started", "thread_id": "session"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "done"}},
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 100, "output_tokens": 10, "cached_input_tokens": 50},
        },
    ]
    result = parse_events("\n".join(json.dumps(event) for event in events))
    assert result.status == "success"
    assert result.summary == "done"
    assert result.session_id == "session"
    assert result.usage.input_tokens == 100
    assert result.usage.reasoning_tokens is None
    assert result.usage.cost_usd is None
    assert CodexProvider().capabilities.cost_reporting is False


def test_codex_rejects_malformed_incomplete_failed_and_invalid_usage() -> None:
    assert parse_events("not json").error_kind == "malformed_output"
    assert parse_events("[]").error_kind == "malformed_output"
    assert parse_events('{"type":"turn.started"}').error_kind == "incomplete_output"
    assert parse_events('{"type":"turn.failed","error":"failure"}').status == "error"
    assert parse_events('{"type":"turn.completed","usage":{"input_tokens":-1}}').status == "error"


def test_codex_normalizes_invalid_nested_event_fields() -> None:
    events = [
        {"type": "thread.started", "thread_id": 123},
        {"type": "item.completed", "item": {"type": "agent_message", "text": None}},
        {"type": "turn.completed", "usage": []},
    ]
    for event in events:
        assert parse_events(json.dumps(event)).error_kind == "malformed_output"

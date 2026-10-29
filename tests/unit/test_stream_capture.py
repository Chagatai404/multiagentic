import asyncio
import json
import sys
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import pytest

from eng.core.models import Check, ProviderRequest
from eng.execution.capture import Capture, JsonStreamRedactor, StreamRedactor
from eng.execution.process import run_process
from eng.providers.claude import ResultBuffer
from eng.providers.codex import CodexProvider, EventParser
from eng.verification.runner import run_checks


def streamed(redactor: StreamRedactor | JsonStreamRedactor, text: str, width: int) -> str:
    return "".join(
        redactor.feed(text[i : i + width]) for i in range(0, len(text), width)
    ) + redactor.feed("", final=True)


@pytest.mark.parametrize("width", [1, 7, 4093, 65536])
def test_secret_boundaries_and_long_values(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    monkeypatch.setenv("EXAMPLE_API_KEY", "environment-secret-123")
    raw = "é environment-secret-123 password=" + "z" * 20000 + "\nBearer " + "a" * 20000 + "\nend"
    clean = streamed(StreamRedactor(), raw, width)
    assert "environment-secret" not in clean
    assert "zzzz" not in clean
    assert "aaaa" not in clean
    assert clean.startswith("é [REDACTED] password=[REDACTED]")
    assert clean.endswith("\nend")


@pytest.mark.parametrize("width", [1, 11, 4093, 65536])
@pytest.mark.parametrize("secret", ["alpha beta gamma", "alpha,beta", 'alpha"beta', "alpha'beta"])
def test_assignment_overlap_and_quoted_values(
    monkeypatch: pytest.MonkeyPatch, width: int, secret: str
) -> None:
    monkeypatch.setenv("TEST_API_KEY", secret)
    for value in (f'password="{secret}"', "password=" + secret):
        clean = streamed(StreamRedactor(), value, width)
        assert "alpha" not in clean
        assert "beta" not in clean
        assert "gamma" not in clean
        raw = json.dumps({"result": value})
        result = json.loads(streamed(JsonStreamRedactor(), raw, width))
        assert "beta" not in result["result"]
        assert "gamma" not in result["result"]
    raw = 'password="' + 'unknown value with \\"escaped quote ' * 700 + '" done'
    clean = streamed(StreamRedactor(), raw, width)
    assert "unknown" not in clean
    assert "escaped" not in clean
    assert clean.endswith('" done')
    clean = streamed(StreamRedactor(), 'password=" two word credential" done', width)
    assert clean == 'password="[REDACTED]" done'


@pytest.mark.parametrize("width", [1, 7, 4096])
@pytest.mark.parametrize("secret", ["0.123456", "-0.123456", "1.23456e-12", "123456"])
def test_json_number_lexemes_and_substring_credentials(
    monkeypatch: pytest.MonkeyPatch, width: int, secret: str
) -> None:
    monkeypatch.setenv("TEST_API_KEY", secret)
    raw = (
        '{"total_cost_usd":0.123456,"negative":-0.123456,"exponent":1.23456e-12,'
        '"substring":123456789,"usage":{"input_tokens":123},'
        '"result":' + json.dumps(secret) + "}"
    )
    result = json.loads(streamed(JsonStreamRedactor(), raw, width))
    assert result["total_cost_usd"] == 0.123456
    assert result["negative"] == -0.123456
    assert result["exponent"] == 1.23456e-12
    assert result["substring"] == 123456789
    assert result["usage"]["input_tokens"] == 123
    assert result["result"] == "[REDACTED]"
    for plaintext in ("password=" + secret, secret, "false " + secret):
        malformed = streamed(JsonStreamRedactor(), plaintext, width)
        assert secret not in malformed


@pytest.mark.parametrize("width", [1, 17, 4096])
def test_json_escaped_secrets_unicode_and_numeric_usage(
    monkeypatch: pytest.MonkeyPatch, width: int
) -> None:
    monkeypatch.setenv("NUMERIC_API_KEY", "123456")
    monkeypatch.setenv("UNICODE_API_KEY", "ABCD😀EFG")
    raw = json.dumps(
        {
            "result": 'ABCD😀EFG api_key="unknown-value"',
            "usage": {"input_tokens": 123456},
            "password": "hidden",
        }
    )
    clean = streamed(JsonStreamRedactor(), raw, width)
    result = json.loads(clean)
    assert "unknown-value" not in result["result"]
    assert "ABCD" not in result["result"]
    assert result["usage"]["input_tokens"] == 123456
    assert result["password"] == "[REDACTED]"


def test_utf8_invalid_bytes_and_metadata(tmp_path: Path) -> None:
    cap = Capture(tmp_path / "out", 30)
    raw = "é😀 password=private-value\n".encode() + b"\xff"
    for item in raw:
        cap.feed(bytes([item]))
    cap.finish()
    assert cap.complete
    assert cap.raw_bytes == len(raw)
    assert (tmp_path / "out").read_text(encoding="utf-8") == "é😀 password=[REDACTED]\n�"
    assert cap.metadata()["excerpt_truncated"] == (cap.redacted_bytes > 30)


def test_ambiguous_long_credential_prefix_fails_closed(tmp_path: Path) -> None:
    cap = Capture(tmp_path / "out", 100)
    cap.feed(b"password" + b" " * 5000)
    cap.feed(b"= never-persist-this")
    cap.finish()
    assert not cap.complete
    assert cap.error is not None
    assert b"never-persist-this" not in (tmp_path / "out").read_bytes()


def test_full_artifact_exceeds_excerpt_and_has_metadata(tmp_path: Path) -> None:
    result = asyncio.run(
        run_process(
            [sys.executable, "-c", "print('x'*2100000);print('TAIL')"],
            tmp_path,
            15,
            output_limit=128,
            stdout_path=tmp_path / "out",
            stderr_path=tmp_path / "err",
        )
    )
    assert result.exit_code == 0
    assert len(result.stdout.encode()) == 128
    assert (tmp_path / "out").read_text().endswith("TAIL\n")
    metadata = json.loads((tmp_path / "out.metadata.json").read_text())
    assert metadata["stdout"]["complete"]
    assert metadata["stdout"]["excerpt_truncated"]
    assert metadata["stdout"]["artifact_bytes"] > 2_000_000


def test_sink_failure_terminates_and_reaps(tmp_path: Path) -> None:
    result = asyncio.run(
        run_process(
            [sys.executable, "-c", 'import time;print("hello",flush=True);time.sleep(30)'],
            tmp_path,
            5,
            stdout_path=tmp_path,
        )
    )
    assert result.reason == "artifact_error"
    assert result.exit_code is not None
    assert result.duration_seconds < 5
    assert result.capture_metadata is not None
    assert not result.capture_metadata["stdout"]["complete"]


@pytest.mark.parametrize("failure", ["write", "close"])
def test_sink_write_and_close_errors_mark_incomplete(failure: str) -> None:
    class BrokenSink:
        closed = False

        def write(self, data: bytes) -> int:
            if failure == "write":
                raise OSError("disk full")
            return len(data)

        def close(self) -> None:
            self.closed = True
            if failure == "close":
                raise OSError("flush failed")

    sink = BrokenSink()
    cap = Capture(None, 128)
    cap.sink = sink  # type: ignore[assignment]
    cap.feed(b"safe data")
    cap.finish()
    assert sink.closed
    assert not cap.complete
    assert cap.error == "OSError"


def test_codex_late_usage_after_large_output_and_failed_event() -> None:
    parser = EventParser()
    for _ in range(300):
        parser.feed(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "command_execution", "text": "x" * 10000},
                }
            )
            + "\n"
        )
    parser.feed('{"type":"turn.failed","error":"failure"}\n')
    parser.feed('{"type":"turn.completed","usage":{"input_tokens":91,"output_tokens":7}}\n')
    result = parser.finish()
    assert result.status == "error"
    assert result.usage.input_tokens == 91


def test_oversized_protocol_explicit_and_late_codex_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("eng.providers.codex.MAX_RECORD_CHARS", 40)
    parser = EventParser()
    parser.feed("x" * 100 + "\n")
    monkeypatch.setattr("eng.providers.codex.MAX_RECORD_CHARS", 400)
    parser.feed('{"type":"turn.completed","usage":{"output_tokens":5}}\n')
    result = parser.finish()
    assert result.error_kind == "oversized_output"
    assert result.usage.output_tokens == 5
    monkeypatch.setattr("eng.providers.claude.MAX_RESULT_CHARS", 40)
    buffer = ResultBuffer()
    buffer.feed("x" * 41)
    assert buffer.parse(0).error_kind == "oversized_output"
    assert not buffer.parts


@pytest.mark.parametrize("startup_seconds", [0, 1.0])
def test_timeout_preserves_observed_codex_usage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, startup_seconds: float
) -> None:
    # Exercise the real stream and process cleanup, but start the timeout only
    # after usage is observed. Interpreter startup speed is not this contract.
    # Patch only the transport clock, leaving asyncio's scheduling clock intact.
    observed = False
    started = monotonic()
    original_feed = EventParser.feed

    def observe_usage(parser: EventParser, text: str) -> None:
        nonlocal observed
        original_feed(parser, text)
        observed = parser.usage.output_tokens == 9

    def transport_clock() -> float:
        # Missing fixture output must still terminate under a real-time watchdog.
        return started + (2.0 if observed or monotonic() - started >= 10 else 0.0)

    monkeypatch.setattr(EventParser, "feed", observe_usage)
    monkeypatch.setattr("eng.execution.process.time", SimpleNamespace(monotonic=transport_clock))
    script = tmp_path / "provider.py"
    script.write_text(
        f"import time\ntime.sleep({startup_seconds})\n"
        'print(\'{"type":"turn.completed","usage":{"output_tokens":9}}\','
        "flush=True)\ntime.sleep(30)\n"
    )
    monkeypatch.setattr("eng.providers.codex.codex_command", lambda: [sys.executable, str(script)])
    request = ProviderRequest(
        task_id="t", execution_id="e", workspace=tmp_path, prompt="x", timeout_seconds=0.8
    )
    result = asyncio.run(CodexProvider().execute(request, tmp_path / "a", lambda: False))
    assert observed, "Fixture never delivered its usage event before the watchdog"
    assert result.status == "timeout"
    assert result.usage.output_tokens == 9
    assert (tmp_path / "a/provider.jsonl").exists()


def test_verification_output_is_complete(tmp_path: Path) -> None:
    check = Check(
        name="large",
        argv=[
            sys.executable,
            "-c",
            "print('x'*2100000);print('LAST');import sys;print('ERR',file=sys.stderr)",
        ],
        confirmed=True,
        timeout_seconds=15,
    )
    results = asyncio.run(run_checks(tmp_path, [check], tmp_path / "checks", lambda: False, 20))
    assert results[0].outcome == "PASS"
    assert "LAST\n" in (tmp_path / "checks/large.log").read_text()
    assert "STDERR:\nERR" in (tmp_path / "checks/large.log").read_text()
    assert "ERR" in (tmp_path / "checks/large.stderr.log").read_text()

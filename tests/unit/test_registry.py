import asyncio
from pathlib import Path

import pytest

from eng.execution.process import ProcessResult
from eng.providers.fake import FakeProvider
from eng.providers.registry import ProviderRegistration, ProviderRegistry, build_registry


def test_registry_invariants_and_factories() -> None:
    registry = ProviderRegistry()
    calls = []

    def factory() -> FakeProvider:
        calls.append(True)
        return FakeProvider()

    registration = ProviderRegistration("fake", factory)
    registry.register(registration)
    assert registry.names() == ("fake",)
    assert calls == []
    assert registry.create("fake").name == "fake"
    assert len(calls) == 1
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(registration)
    for name in ("", "Bad", "bad name", "../x"):
        with pytest.raises(ValueError, match="Invalid"):
            registry.register(ProviderRegistration(name, factory))
    with pytest.raises(ValueError, match="Unknown provider"):
        registry.create("missing")
    registry.register(ProviderRegistration("other", factory))
    with pytest.raises(ValueError, match="returned fake"):
        registry.create("other")


def test_capabilities_do_not_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> list[str]:
        raise AssertionError("must not probe")

    monkeypatch.setattr("eng.providers.registry.run_process", forbidden)
    registry = build_registry()
    assert registry.names() == ("claude", "codex", "fake")
    registry.register(ProviderRegistration("extra", lambda: FakeProvider(), forbidden))
    # The factory mismatch remains explicit even during capability discovery.
    with pytest.raises(ValueError, match="returned fake"):
        registry.capabilities()
    assert set(build_registry().capabilities()) == {"claude", "codex", "fake"}


@pytest.mark.parametrize(
    "reason,exit_code,available",
    [(None, 0, True), (None, 1, False), ("timeout", 0, False), ("unavailable", None, False)],
)
def test_doctor_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reason: str | None,
    exit_code: int | None,
    available: bool,
) -> None:
    async def probe(argv: list[str], cwd: Path, probe_seconds: float) -> ProcessResult:
        assert argv == ["adapter", "--version"]
        assert cwd == tmp_path
        assert probe_seconds == 0.2
        return ProcessResult(exit_code, "v1\n", "failure", 0, reason)

    monkeypatch.setattr("eng.providers.registry.run_process", probe)
    registry = ProviderRegistry()
    registry.register(ProviderRegistration("fake", FakeProvider))
    registry.register(ProviderRegistration("adapter", FakeProvider, lambda: ["adapter"]))
    result = asyncio.run(registry.doctor(tmp_path, timeout_seconds=0.2))
    assert result["adapter"]["available"] is available
    assert result["adapter"]["authentication"] == "not_checked"
    assert result["adapter"]["reason"] == reason
    assert result["fake"]["kind"] == "deterministic_fixture"


def test_doctor_resolution_and_timeout_validation(tmp_path: Path) -> None:
    def missing() -> list[str]:
        raise ValueError("missing executable")

    registry = ProviderRegistry()
    registry.register(ProviderRegistration("missing", FakeProvider, missing))
    result = asyncio.run(registry.doctor(tmp_path))
    assert result["missing"]["available"] is False
    for timeout in (0, -1, float("inf"), float("nan")):
        with pytest.raises(ValueError, match="finite and positive"):
            asyncio.run(registry.doctor(tmp_path, timeout_seconds=timeout))

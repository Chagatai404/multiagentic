"""Explicit provider factories and bounded, non-model availability probes."""

import asyncio
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from eng.core.models import Capabilities
from eng.execution.process import redact, run_process
from eng.providers.base import Provider
from eng.providers.claude import ClaudeProvider, claude_command
from eng.providers.codex import CodexProvider, codex_command
from eng.providers.fake import FakeProvider


@dataclass(frozen=True)
class ProviderRegistration:
    name: str
    factory: Callable[[], Provider]
    command: Callable[[], list[str]] | None = None


class ProviderRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, ProviderRegistration] = {}

    def register(self, registration: ProviderRegistration) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", registration.name):
            raise ValueError(f"Invalid provider name: {registration.name!r}")
        if registration.name in self._registrations:
            raise ValueError(f"Duplicate provider: {registration.name}")
        self._registrations[registration.name] = registration

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._registrations))

    def create(self, name: str) -> Provider:
        if name not in self._registrations:
            raise ValueError(f"Unknown provider: {name}; choose {', '.join(self.names())}")
        provider = self._registrations[name].factory()
        if provider.name != name:
            raise ValueError(f"Provider factory for {name} returned {provider.name}")
        return provider

    def capabilities(self) -> dict[str, Capabilities]:
        return {name: self.create(name).capabilities for name in self.names()}

    async def doctor(
        self, cwd: Path, *, timeout_seconds: float = 15
    ) -> dict[str, dict[str, object]]:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Probe timeout must be finite and positive")

        async def inspect(name: str) -> tuple[str, dict[str, object]]:
            registration = self._registrations[name]
            result: dict[str, object] = {"authentication": "not_checked"}
            if registration.command is None:
                result.update(available=True, kind="deterministic_fixture")
                return name, result
            try:
                command = registration.command()
                if not command:
                    raise ValueError("Empty provider command")
                version = await run_process([*command, "--version"], cwd, timeout_seconds)
                result.update(
                    available=version.exit_code == 0 and version.reason is None,
                    version=redact(version.stdout.strip()),
                    error=redact(version.stderr[-1000:]),
                    reason=version.reason,
                )
            except (ValueError, OSError) as error:
                result.update(available=False, error=redact(str(error)), reason="unavailable")
            return name, result

        return dict(await asyncio.gather(*(inspect(name) for name in self.names())))


def build_registry(*, fake_changes: dict[str, str] | None = None) -> ProviderRegistry:
    changes = dict(fake_changes or {})
    registry = ProviderRegistry()
    registry.register(ProviderRegistration("fake", lambda: FakeProvider(dict(changes))))
    registry.register(ProviderRegistration("codex", CodexProvider, codex_command))
    registry.register(ProviderRegistration("claude", ClaudeProvider, claude_command))
    return registry

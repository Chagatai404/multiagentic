"""Declarative coding-CLI provider configured in ``project.yaml`` (``command_providers``).

eng bakes in no vendor flags: the project supplies the argv, the task prompt is written to
stdin, the process runs in the task worktree with a scrubbed environment and a bounded,
redacted capture. Exit code, timeout and cancellation map onto the common
ProviderResult; usage and cost are never invented.
"""

import shutil
from collections.abc import Callable
from pathlib import Path

from eng.core.models import (
    Capabilities,
    CommandProviderConfig,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
)
from eng.execution.commands import resolve_command
from eng.execution.process import redact, run_process

MAX_SUMMARY_CHARS = 64_000


def locate(config: CommandProviderConfig) -> str | None:
    """Find the executable without running anything."""
    executable = resolve_command(list(config.argv))[0]
    return shutil.which(executable)


class CommandProvider:
    capabilities = Capabilities(kind="coding_cli", file_editing=True)

    def __init__(self, name: str, config: CommandProviderConfig) -> None:
        self.name = name
        self.config = config
        self.capabilities = Capabilities(
            kind="coding_cli", file_editing=True, model_selection=config.model_flag is not None
        )

    async def execute(
        self,
        request: ProviderRequest,
        artifact_dir: Path,
        cancelled: Callable[[], bool],
    ) -> ProviderResult:
        try:
            command = resolve_command(list(self.config.argv))
        except ValueError as error:
            return ProviderResult(status="error", error_kind="unavailable", summary=str(error))
        if request.model:
            if not self.config.model_flag:
                return ProviderResult(
                    status="error",
                    error_kind="model_unsupported",
                    summary=f"Provider {self.name} declares no model_flag",
                )
            command += [self.config.model_flag, request.model]
        result = await run_process(
            command,
            request.workspace,
            request.timeout_seconds,
            stdin=request.prompt,
            cancelled=cancelled,
            stdout_path=artifact_dir / "provider.log",
            stderr_path=artifact_dir / "provider.stderr.log",
            env_allow=self.config.env_allow,
        )
        if result.reason:
            status: ProviderStatus = "error"
            if result.reason == "cancelled":
                status = "cancelled"
            elif result.reason == "timeout":
                status = "timeout"
            return ProviderResult(
                status=status,
                error_kind=result.reason,
                summary=redact(result.stderr[-4000:]),
                duration_seconds=result.duration_seconds,
            )
        if result.exit_code != 0:
            return ProviderResult(
                status="error",
                error_kind="exit_code",
                summary=redact(result.stderr[-4000:] or result.stdout[-4000:]),
                duration_seconds=result.duration_seconds,
            )
        return ProviderResult(
            status="success",
            summary=redact(result.stdout)[:MAX_SUMMARY_CHARS],
            duration_seconds=result.duration_seconds,
        )

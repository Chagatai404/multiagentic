import sys
import time
from collections.abc import Callable
from pathlib import Path

from eng.core.models import Check, VerificationResult
from eng.execution.process import redact, run_process


async def run_checks(
    workspace: Path,
    checks: list[Check],
    artifact_dir: Path,
    cancelled: Callable[[], bool],
    remaining_seconds: float,
) -> list[VerificationResult]:
    artifact_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - bounded local evidence
    results: list[VerificationResult] = []
    started = time.monotonic()
    for check in checks:
        remaining = remaining_seconds - (time.monotonic() - started)
        evidence = VerificationResult(
            check_id=check.name,
            command=check.argv,
            environment=str(workspace),
            required=check.required,
            outcome="SKIPPED",
        )
        if not check.confirmed:
            evidence.reason = "Command is unconfirmed; review project.yaml"
            results.append(evidence)
            continue
        if cancelled() or remaining <= 0:
            reason = "cancelled" if cancelled() else "wall-clock budget exhausted"
            evidence.reason = reason
            results.append(evidence)
            continue
        argv = [sys.executable if part == "{python}" else part for part in check.argv]
        result = await run_process(
            argv, workspace, min(check.timeout_seconds, remaining), cancelled=cancelled
        )
        log = artifact_dir / f"{check.name}.log"
        log.write_text(redact(result.stdout + "\nSTDERR:\n" + result.stderr), encoding="utf-8")
        evidence.exit_code = result.exit_code
        evidence.duration_seconds = result.duration_seconds
        evidence.artifact = str(log)
        evidence.reason = result.reason
        evidence.outcome = "PASS" if result.exit_code == 0 and not result.reason else "FAIL"
        if result.reason == "unavailable":
            evidence.outcome = "UNAVAILABLE"
        elif result.reason:
            evidence.outcome = "ERROR"
        results.append(evidence)
    return results

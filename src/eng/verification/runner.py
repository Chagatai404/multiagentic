import shutil
import time
from collections.abc import Callable
from pathlib import Path

from eng.core.models import Check, VerificationResult
from eng.execution.capture import save_metadata
from eng.execution.commands import resolve_command
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
        try:
            argv = resolve_command(check.argv)
        except ValueError as error:
            evidence.outcome = "UNAVAILABLE"
            evidence.reason = str(error)
            results.append(evidence)
            continue
        log = artifact_dir / f"{check.name}.log"
        result = await run_process(
            argv, workspace, min(check.timeout_seconds, remaining), cancelled=cancelled,
            stdout_path=log,
            stderr_path=artifact_dir / f"{check.name}.stderr.log",
        )
        if result.capture_metadata is None:
            log.write_text(redact(result.stdout + "\nSTDERR:\n" + result.stderr), encoding="utf-8")
        else:
            # Keep the established combined check evidence contract. Both inputs
            # were already redacted before disk; copying never retains a full log.
            try:
                with log.open("ab") as combined:
                    combined.write(b"\nSTDERR:\n")
                    with (artifact_dir / f"{check.name}.stderr.log").open("rb") as errors:
                        shutil.copyfileobj(errors, combined, length=65536)
                result.capture_metadata["combined"] = {
                    "artifact_bytes": log.stat().st_size,
                    "complete": all(
                        stream.get("complete") for stream in result.capture_metadata.values()
                    ),
                    "process_reason": result.reason,
                }
                save_metadata(log.with_name(log.name + ".metadata.json"), result.capture_metadata)
            except OSError:
                evidence.reason = "artifact_error"
        evidence.exit_code = result.exit_code
        evidence.duration_seconds = result.duration_seconds
        evidence.artifact = str(log)
        evidence.reason = evidence.reason or result.reason
        evidence.outcome = "PASS" if result.exit_code == 0 and not result.reason else "FAIL"
        if result.reason == "unavailable":
            evidence.outcome = "UNAVAILABLE"
        elif evidence.reason:
            evidence.outcome = "ERROR"
        results.append(evidence)
    return results

import asyncio
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eng.execution.windows_job import WindowsJob

SECRET_NAMES = re.compile(r"(?:token|secret|password|api.?key|credential|private.?key)", re.I)
SECRET_PAIR = re.compile(
    r"(?i)([\"']?(?:[\w-]*[_-])?(?:token|secret|password|api[_-]?key|credential|private[_-]?key)"
    r"[\"']?\s*[:=]\s*[\"']?)([^\s\"',}]+)"
)


def redact(text: str) -> str:
    for key, value in os.environ.items():
        if SECRET_NAMES.search(key) and len(value) >= 6:
            text = text.replace(value, "[REDACTED]")
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+", r"\1[REDACTED]", text)
    return SECRET_PAIR.sub(r"\1[REDACTED]", text)


def redact_data(value: Any) -> Any:
    """Redact string values before JSON serialization, preserving numeric usage and syntax."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: redact_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    return value


def clean_environment(*, provider: bool = False) -> dict[str, str]:
    # Project checks must not inherit the host's API keys or arbitrary environment values.
    allowed = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "LANG",
        "LC_ALL",
    }
    if provider:
        allowed |= {"CODEX_HOME", "OPENAI_API_KEY", "CODEX_API_KEY"}
    result = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    result.update({"GIT_TERMINAL_PROMPT": "0", "ENG_ACTIVE": "1", "PYTHONIOENCODING": "utf-8"})
    return result


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    reason: str | None = None


async def stop_tree(process: asyncio.subprocess.Process, job: WindowsJob | None = None) -> None:
    if job is not None:
        job.close()
    elif sys.platform == "win32":
        # taskkill is an executable, not a shell command. /T includes descendants.
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/PID",
            str(process.pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await killer.wait()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.wait()


async def run_process(
    argv: list[str],
    cwd: Path,
    timeout: float,  # noqa: ASYNC109 - poll cancellation and enforce a shared deadline
    *,
    stdin: str | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    provider: bool = False,
    output_limit: int = 2_000_000,
) -> ProcessResult:
    started = time.monotonic()
    options: dict[str, object] = {}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=clean_environment(provider=provider),
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **options,  # type: ignore[arg-type]
        )
    except (OSError, ValueError) as error:
        return ProcessResult(
            None, "", redact(str(error)), time.monotonic() - started, "unavailable"
        )

    job = None
    if sys.platform == "win32":
        try:
            job = WindowsJob(process.pid)
        except OSError as error:
            await stop_tree(process)
            return ProcessResult(
                None, "", redact(str(error)), time.monotonic() - started, "process_isolation"
            )

    async def drain(stream: asyncio.StreamReader | None) -> str:
        chunks = bytearray()
        if stream is not None:
            while chunk := await stream.read(65536):
                # Keep draining after the retention limit to avoid pipe deadlocks.
                chunks.extend(chunk[: max(0, output_limit - len(chunks))])
        return chunks.decode("utf-8", errors="replace")

    async def communicate() -> tuple[str, str]:
        output = asyncio.gather(drain(process.stdout), drain(process.stderr))
        if stdin is not None and process.stdin is not None:
            try:
                process.stdin.write(stdin.encode("utf-8"))
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()
        out, err = await output
        await process.wait()
        return out, err

    communication = asyncio.create_task(communicate())
    reason = None
    try:
        while not communication.done():
            if cancelled():
                reason = "cancelled"
                break
            if time.monotonic() - started >= timeout:
                reason = "timeout"
                break
            await asyncio.wait({communication}, timeout=min(0.1, timeout))
        if reason:
            await stop_tree(process, job)
        stdout, stderr = await communication
    except BaseException:
        await stop_tree(process, job)
        await asyncio.gather(communication, return_exceptions=True)
        raise
    finally:
        if job is not None:
            job.close()
        elif sys.platform != "win32":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    return ProcessResult(process.returncode, stdout, stderr, time.monotonic() - started, reason)

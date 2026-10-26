import asyncio
import hashlib
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from eng.agents.registry import get_role
from eng.core.models import InvocationTelemetry, ProviderRequest, ProviderResult, Task
from eng.execution.workspace import git, protected_changes, safe_path
from eng.providers.base import Provider


def _files(workspace: Path) -> list[tuple[str, Path]]:
    names = git(workspace, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    result = []
    for relative in sorted(set(filter(None, names.split("\0")))):
        # Check every original component: safe_path resolves symlinks, obscuring their identity.
        cursor = workspace
        for part in Path(relative).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("Symlink content is not eligible for role execution")
        path = safe_path(workspace, relative)
        if path.exists():
            if not path.is_file():
                raise ValueError("Only regular repository files are eligible")
            result.append((relative, path))
    return result


def workspace_digest(workspace: Path) -> str:
    """Hash current tracked and nonignored content, including protected files."""
    digest = hashlib.sha256()
    for relative, path in _files(workspace):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(path.stat().st_mode).encode("ascii"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _prepare_snapshot(
    request: ProviderRequest,
    task: Task,
    artifact_dir: Path,
) -> tuple[Path, Path, str, str]:
    original = request.workspace.resolve()
    if artifact_dir.resolve().is_relative_to(original):
        raise ValueError("Read-only role artifacts must be outside its workspace")
    before = workspace_digest(original)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    # A shallow shared root keeps snapshot Git object paths far below Windows MAX_PATH;
    # Git fails there even with core.longpaths. It is ignored runtime state, outside the
    # task worktree; a workspace that is the project itself keeps snapshots by its artifacts.
    root = task.project.resolve() / ".engineering" / "artifacts" / "snapshots"
    if root.is_relative_to(original):
        root = artifact_dir.parent
    snapshot = root / f"{request.role.value[0]}-snapshot-{uuid4().hex[:8]}"
    snapshot.mkdir(parents=True)
    for relative, source in _files(original):
        if protected_changes([relative], task.config.protected_paths):
            continue
        target = safe_path(snapshot, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    git(snapshot, "init", "--quiet")
    git(snapshot, "add", "--force", "--all")
    return original, snapshot, before, workspace_digest(snapshot)


def _mutation(original: Path, snapshot: Path, before: str, snapshot_before: str) -> str | None:
    """Return why read-only content is no longer trusted; unreadable content fails closed."""
    try:
        if workspace_digest(original) != before or workspace_digest(snapshot) != snapshot_before:
            return "Read-only role modified repository content"
    except (ValueError, OSError) as error:
        return str(error)
    return None


async def execute_role(
    provider: Provider,
    request: ProviderRequest,
    task: Task,
    artifact_dir: Path,
    cancelled: Callable[[], bool],
) -> ProviderResult:
    """Detect read-only role mutations; retained snapshots are not OS sandboxes."""
    definition = get_role(request.role)
    if definition.deterministic:
        raise ValueError("Verifier executes configured checks, never a provider")

    measured_request: InvocationTelemetry | None = None

    async def invoke(actual_request: ProviderRequest) -> ProviderResult:
        nonlocal measured_request
        measured_request = InvocationTelemetry(
            provider_invoked=True,
            packet_chars=len(actual_request.prompt),
            packet_utf8_bytes=len(actual_request.prompt.encode("utf-8")),
        )
        result = await provider.execute(actual_request, artifact_dir, cancelled)
        result.telemetry = measured_request
        return result

    if not definition.read_only:
        return await invoke(request)
    if cancelled():
        return ProviderResult(status="cancelled", error_kind="cancelled")
    started = time.monotonic()
    try:
        original, snapshot, before, snapshot_before = await asyncio.to_thread(
            _prepare_snapshot,
            request,
            task,
            artifact_dir,
        )
    except (ValueError, OSError) as error:
        return ProviderResult(status="error", error_kind="role_setup", summary=str(error))
    remaining = request.timeout_seconds - (time.monotonic() - started)
    if cancelled():
        return ProviderResult(status="cancelled", error_kind="cancelled")
    if remaining <= 0:
        return ProviderResult(
            status="timeout",
            error_kind="timeout",
            summary="Read-only role setup exhausted the invocation timeout",
        )
    prompt = request.prompt
    for path in (original, task.project):
        for value in (str(path), path.as_posix()):
            prompt = prompt.replace(value, "[task workspace]")
    isolated = request.model_copy(
        update={
            "workspace": snapshot,
            "prompt": prompt,
            "timeout_seconds": remaining,
        }
    )
    arguments = (original, snapshot, before, snapshot_before)
    try:
        result = await invoke(isolated)
    except Exception:
        # A detected mutation outranks the provider failure: fail closed and record it.
        if mutation := await asyncio.to_thread(_mutation, *arguments):
            return ProviderResult(
                status="error",
                error_kind="role_mutation",
                summary=mutation,
                telemetry=measured_request,
            )
        raise
    if mutation := await asyncio.to_thread(_mutation, *arguments):
        return result.model_copy(
            update={"status": "error", "error_kind": "role_mutation", "summary": mutation}
        )
    return result

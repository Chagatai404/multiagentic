import fnmatch
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from eng.core.models import Task


def git(repository: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            # Windows Git otherwise fails beyond MAX_PATH in deep worktrees and role snapshots.
            ["git", "-c", "core.longpaths=true", "-C", str(repository), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"Git operation timed out: {arguments[0]}") from error
    if result.returncode:
        raise ValueError(result.stderr.strip() or "Git operation failed")
    return result.stdout.strip()


def repository_root(path: Path) -> Path:
    return Path(git(path.resolve(), "rev-parse", "--show-toplevel")).resolve()


def prepare(task: Task) -> Path:
    if git(task.project, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("Repository must be clean; commit or preserve existing changes first")
    task.base_commit = git(task.project, "rev-parse", "HEAD")
    workspace = task.project / ".engineering" / "worktrees" / task.id
    if workspace.exists():
        raise ValueError("Workspace already exists; inspect it before continuing")
    workspace.parent.mkdir(parents=True, exist_ok=True)
    git(task.project, "worktree", "add", "--detach", str(workspace), task.base_commit)
    task.workspace = workspace
    return workspace


def safe_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or any(part.lower() == ".git" for part in candidate.parts)
    ):
        raise ValueError(f"Unsafe repository path: {relative}")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes workspace: {relative}")
    return resolved


def changed_paths(workspace: Path, base: str) -> list[str]:
    tracked = git(workspace, "diff", "--name-only", "-z", base)
    untracked = git(workspace, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted(set(item for item in (tracked + "\0" + untracked).split("\0") if item))


def protected_changes(paths: list[str], patterns: list[str]) -> list[str]:
    # Mandatory restrictions cannot be weakened in project configuration.
    patterns = [".git", ".engineering", ".env", ".env.*", "*.pem", "*.key", *patterns]
    return [
        path
        for path in paths
        if any(
            fnmatch.fnmatchcase(path.lower(), pattern.lower())
            or path.lower().startswith(pattern.lower().rstrip("/") + "/")
            or fnmatch.fnmatchcase(Path(path).name.lower(), pattern.lower())
            for pattern in patterns
        )
    ]


@contextmanager
def task_lock(project: Path, task_id: str) -> Iterator[None]:
    """OS lock releases on crash; lock files are never removed underneath another waiter."""
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", task_id):
        raise ValueError("Invalid task identifier")
    directory = project / ".engineering" / "locks"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"{task_id}.lock").open("a+b") as handle:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("This task is already running in another process") from error
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def save_diff(task: Task, directory: Path) -> None:
    if task.workspace is None or task.base_commit is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
    # Redacted diff is inspection evidence, never advertised as an apply-ready patch.
    from eng.execution.process import redact

    (directory / "changes.diff").write_text(
        redact(git(task.workspace, "diff", "--binary", task.base_commit)), encoding="utf-8"
    )
    (directory / "changed-files.json").write_text(
        json.dumps(changed_paths(task.workspace, task.base_commit), indent=2), encoding="utf-8"
    )

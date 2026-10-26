"""Git hook entry point: ``python -m eng.integrations.githook EVENT [--block] [--project P]``.

``post-commit`` and ``pre-push`` hooks installed by ``eng hooks git install`` call this.
It fails open: any internal problem prints a warning to stderr and exits 0. The only
non-zero exit is an explicit ``--block`` pre-push whose synchronous verification produced
a definitive FAIL (INCOMPLETE verification never blocks a push). Inside an eng-launched
process (``ENG_ACTIVE``) it does nothing, so agent commits cannot recurse.
"""

import os
import sys
from pathlib import Path

ZERO = "0" * 40
MAX_PUSHED_COMMITS = 5


# Variables Git exports to hooks that point at *this* repository's internals. Inherited by
# a detached verifier or a nested git call they would redirect worktree/index operations.
_LOCAL_GIT_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_PREFIX",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_QUARANTINE_PATH",
    "GIT_CEILING_DIRECTORIES_DISABLED",
)


def _scrub_git_environment() -> None:
    for name in _LOCAL_GIT_ENV:
        os.environ.pop(name, None)


def _parse(arguments: list[str]) -> tuple[str, bool, Path | None]:
    event = arguments[0] if arguments else ""
    block = "--block" in arguments
    project = None
    if "--project" in arguments and arguments.index("--project") + 1 < len(arguments):
        project = Path(arguments[arguments.index("--project") + 1])
    return event, block, project


def _pushed_commits(stream: str) -> list[str]:
    commits: list[str] = []
    for line in stream.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[1].strip("0") and parts[1] not in commits:
            commits.append(parts[1])  # skip deletions (all-zero local sha)
    return commits[:MAX_PUSHED_COMMITS]


def _detach(root: Path, rev: str, origin: str) -> None:
    from eng.integrations.runner import spawn_detached

    argv = [
        sys.executable,
        "-m",
        "eng",
        "verify-ref",
        rev,
        "--project",
        str(root),
        "--origin",
        origin,
    ]
    spawn_detached(argv, cwd=root, log_path=root / ".engineering" / "artifacts" / "hooks.log")


def run(event: str, block: bool, project: Path | None, stdin_text: str) -> int:
    if os.environ.get("ENG_ACTIVE"):
        return 0
    _scrub_git_environment()
    from eng.core.refs import ref_outcome  # noqa: F401 - import failures fail open below
    from eng.execution.workspace import repository_root
    from eng.projects.config import load_config
    from eng.storage.store import Store

    root = repository_root(project or Path.cwd())
    if event == "post-commit":
        _detach(root, "HEAD", "post-commit")
        return 0
    if event != "pre-push":
        raise ValueError(f"Unsupported git event: {event}")
    commits = _pushed_commits(stdin_text)
    if not block:
        for commit in commits:
            _detach(root, commit, "pre-push")
        return 0
    from eng.integrations.gitref import verify_ref

    config = load_config(root)
    store = Store(root)
    try:
        failed = []
        for commit in commits:
            record = verify_ref(store, root, commit, config, origin="pre-push")
            print(
                f"eng: {commit[:12]} verification {record.status}: {record.message}",
                file=sys.stderr,
            )
            if record.status == "FAIL":
                failed.append(commit[:12])
    finally:
        store.close()
    if failed:
        print("eng: push blocked by failing required checks: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


def main(arguments: list[str] | None = None) -> int:
    event, block, project = _parse(sys.argv[1:] if arguments is None else arguments)
    try:
        stdin_text = "" if event != "pre-push" else sys.stdin.read()
        return run(event, block, project, stdin_text)
    except BaseException as error:  # noqa: BLE001 - a hook must not break git on its own failure
        print(
            f"eng hook did not run ({event}): {type(error).__name__}: {str(error)[:200]}",
            file=sys.stderr,
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

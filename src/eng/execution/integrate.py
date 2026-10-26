"""Git primitives for plan integration; no policy and no model/provider knowledge.

Node results are captured as commit objects through a temporary index, so a node's
worktree (HEAD, index and files) is never modified. Merges use ``git merge-tree
--write-tree``, which reports conflicts without touching any worktree. Only the
eng-owned integration worktree is ever reset, and only to commits eng created or
recorded itself. Nothing here pushes, and the user's branch is only moved by
``fast_forward`` after an explicit approval.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from eng.execution.workspace import git, git_result

_IDENTITY = {
    "GIT_AUTHOR_NAME": "eng",
    "GIT_AUTHOR_EMAIL": "eng@localhost",
    "GIT_COMMITTER_NAME": "eng",
    "GIT_COMMITTER_EMAIL": "eng@localhost",
}
MINIMUM_GIT = (2, 40)  # merge-tree --write-tree --merge-base


@dataclass(frozen=True)
class MergeOutcome:
    clean: bool
    tree: str | None
    conflicts: list[str]
    detail: str = ""


def git_version(cwd: Path) -> tuple[int, int]:
    match = re.search(r"(\d+)\.(\d+)", git(cwd, "--version"))
    if match is None:
        raise ValueError("Cannot determine the Git version")
    return int(match.group(1)), int(match.group(2))


def require_merge_tree(cwd: Path) -> None:
    if git_version(cwd) < MINIMUM_GIT:
        raise ValueError("Plan integration needs Git 2.40 or newer (merge-tree --write-tree)")


def plan_branch(plan_id: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{8,64}", plan_id):
        raise ValueError("Invalid plan identifier")
    return f"eng/plan/{plan_id}"


def create_integration(root: Path, plan_id: str) -> tuple[str, str, Path]:
    """Create the eng-owned branch and worktree at the checkout's HEAD.

    Returns (branch, base commit, worktree). The user's checkout must be clean so the
    base is exactly what a reviewer sees.
    """
    require_merge_tree(root)
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("Repository must be clean; commit or preserve existing changes first")
    branch = plan_branch(plan_id)
    base = git(root, "rev-parse", "HEAD")
    workspace = root / ".engineering" / "worktrees" / f"plan-{plan_id}"
    if workspace.exists():
        raise ValueError("Integration workspace already exists; inspect it before continuing")
    workspace.parent.mkdir(parents=True, exist_ok=True)
    git(root, "worktree", "add", "-b", branch, str(workspace), base)
    return branch, base, workspace


def head(repository: Path, ref: str = "HEAD") -> str:
    return git(repository, "rev-parse", "--verify", f"{ref}^{{commit}}")


def snapshot_commit(workspace: Path, base: str, scratch: Path, message: str) -> str:
    """Commit the workspace's tracked and unignored content on top of ``base``.

    Uses a throwaway index file, so the worktree's own HEAD, index and files are untouched.
    """
    scratch.mkdir(parents=True, exist_ok=True)
    index = scratch / "snapshot.index"
    index.unlink(missing_ok=True)
    env = {**_IDENTITY, "GIT_INDEX_FILE": str(index)}
    try:
        git(workspace, "read-tree", base, env=env)
        git(workspace, "add", "-A", env=env)
        tree = git(workspace, "write-tree", env=env)
        return git(workspace, "commit-tree", tree, "-p", base, "-m", message, env=env)
    finally:
        index.unlink(missing_ok=True)


def changed_between(repository: Path, old: str, new: str) -> list[str]:
    """Paths that differ, with renames split so both sides are visible."""
    output = git(repository, "diff", "--name-only", "--no-renames", "-z", old, new)
    return sorted(item for item in output.split("\0") if item)


def merge_tree(repository: Path, current: str, incoming: str, base: str) -> MergeOutcome:
    code, stdout, stderr = git_result(
        repository,
        "merge-tree",
        "--write-tree",
        "--name-only",
        f"--merge-base={base}",
        current,
        incoming,
    )
    lines = stdout.splitlines()
    if code == 0 and lines:
        return MergeOutcome(True, lines[0].strip(), [])
    if code == 1 and lines:
        conflicts: list[str] = []
        for line in lines[1:]:
            if not line.strip():
                break  # informational messages follow the blank line
            conflicts.append(line.strip())
        return MergeOutcome(False, None, conflicts or ["(unspecified)"], stderr.strip())
    raise ValueError(stderr.strip() or "git merge-tree failed")


def commit_tree(repository: Path, tree: str, parent: str, message: str) -> str:
    return git(repository, "commit-tree", tree, "-p", parent, "-m", message, env=_IDENTITY)


def reset_integration(workspace: Path, commit: str) -> None:
    """Move the eng-owned integration branch and files to ``commit``.

    The integration worktree holds only eng-created content, so untracked leftovers
    from verification checks may be removed here (never in any other workspace).
    """
    git(workspace, "reset", "--hard", commit)
    git(workspace, "clean", "-fdq")


def is_ancestor(repository: Path, ancestor: str, descendant: str) -> bool:
    code, _, _ = git_result(repository, "merge-base", "--is-ancestor", ancestor, descendant)
    if code not in {0, 1}:
        raise ValueError("git merge-base --is-ancestor failed")
    return code == 0


def current_branch(repository: Path) -> str | None:
    code, stdout, _ = git_result(repository, "symbolic-ref", "-q", "--short", "HEAD")
    return stdout.strip() if code == 0 and stdout.strip() else None


def fast_forward(repository: Path, commit: str) -> None:
    """Advance the checked-out branch; refuses anything that is not a fast-forward."""
    git(repository, "merge", "--ff-only", commit, env=_IDENTITY)

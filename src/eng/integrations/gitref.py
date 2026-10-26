"""Verify a commit in a throwaway worktree with the project's confirmed checks.

Used by the Git hooks and ``eng verify-ref``. The configuration comes from the user's
checkout, never from the commit under test, so a commit cannot weaken its own checks.
No model runs; the worktree is created and removed by this module only.
"""

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

from eng.core.models import ProjectConfig, identity
from eng.core.refs import RefCheck, ref_outcome
from eng.execution.workspace import git
from eng.scheduling.runner import SlotPool
from eng.storage.store import Store
from eng.verification.runner import run_checks

SLOT_WAIT_SECONDS = 120.0


def verify_ref(
    store: Store,
    root: Path,
    rev: str,
    config: ProjectConfig,
    *,
    origin: str = "manual",
    cancelled: Callable[[], bool] = lambda: False,
    wait_seconds: float = SLOT_WAIT_SECONDS,
) -> RefCheck:
    commit = git(root, "rev-parse", "--verify", f"{rev}^{{commit}}")
    check_id = identity()
    pool = SlotPool(root)
    deadline = time.monotonic() + wait_seconds
    slot = pool.acquire()
    while slot is None and time.monotonic() < deadline:
        time.sleep(0.2)
        slot = pool.acquire()
    if slot is None:
        record = RefCheck(
            id=check_id,
            rev=rev,
            commit=commit,
            origin=origin,
            status="INCOMPLETE",
            message="No verification slot became free; nothing was run",
        )
        store.record_ref_check(record)
        return record
    workspace = root / ".engineering" / "worktrees" / f"ref-{check_id}"
    created = False
    try:
        workspace.parent.mkdir(parents=True, exist_ok=True)
        git(root, "worktree", "add", "--detach", str(workspace), commit)
        created = True
        budget = config.budgets.wall_seconds
        results = asyncio.run(
            run_checks(
                workspace,
                config.checks,
                root / ".engineering" / "artifacts" / "refs" / check_id,
                cancelled,
                budget,
            )
        )
        status, message = ref_outcome(results)
    except (ValueError, OSError) as error:
        results, status, message = [], "INCOMPLETE", f"Verification could not run: {error}"
    finally:
        pool.release(slot)
        if created:
            try:
                # Only the worktree this call created, identified by its own unique name.
                git(root, "worktree", "remove", "--force", str(workspace))
            except ValueError:
                pass
    record = RefCheck(
        id=check_id,
        rev=rev,
        commit=commit,
        origin=origin,
        status=status,
        message=message,
        results=results,
    )
    store.record_ref_check(record)
    return record

"""Install, remove and inspect eng's Git hooks (``post-commit`` and ``pre-push``).

A hook file is eng's only if it carries the marker line. Existing foreign hooks are never
overwritten or removed: installation refuses and says so. Hooks are plain POSIX ``sh``
scripts (Git for Windows runs them too) that execute the recorded Python interpreter.
"""

import os
import shlex
import sys
from pathlib import Path
from typing import Any

from eng.execution.workspace import git

MARKER = "# eng-managed-hook v1"
EVENTS = ("post-commit", "pre-push")


def hooks_directory(root: Path) -> Path:
    return Path(git(root, "rev-parse", "--path-format=absolute", "--git-path", "hooks"))


def hook_script(event: str, root: Path, *, block: bool) -> str:
    argv = [sys.executable, "-m", "eng.integrations.githook", event, "--project", str(root)]
    if block:
        argv.append("--block")
    note = "# Installed by `eng hooks git install`; remove with `eng hooks git uninstall`."
    return f"#!/bin/sh\n{MARKER}\n{note}\nexec {shlex.join(argv)}\n"


def _is_eng(path: Path) -> bool:
    try:
        return MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def install(root: Path, events: list[str], *, block: bool) -> dict[str, Any]:
    if block and "pre-push" not in events:
        raise ValueError("--block applies to the pre-push hook")
    directory = hooks_directory(root)
    for event in events:
        if event not in EVENTS:
            raise ValueError(f"Unsupported git event: {event}")
        target = directory / event
        if target.exists() and not _is_eng(target):
            raise ValueError(
                f"{target} already exists and is not managed by eng; "
                f"call `python -m eng.integrations.githook {event}` from it yourself"
            )
    directory.mkdir(parents=True, exist_ok=True)
    installed = []
    for event in events:
        target = directory / event
        target.write_text(
            hook_script(event, root, block=block and event == "pre-push"), encoding="utf-8"
        )
        target.chmod(0o755)
        installed.append(str(target))
    return {"installed": installed, "blocking_pre_push": block}


def uninstall(root: Path) -> dict[str, Any]:
    directory = hooks_directory(root)
    removed, kept = [], []
    for event in EVENTS:
        target = directory / event
        if not target.exists():
            continue
        if _is_eng(target):
            target.unlink()
            removed.append(str(target))
        else:
            kept.append(str(target))
    return {"removed": removed, "kept_foreign": kept}


def status(root: Path) -> dict[str, Any]:
    directory = hooks_directory(root)
    report: dict[str, Any] = {}
    for event in EVENTS:
        target = directory / event
        if not target.exists():
            report[event] = {"installed": False}
            continue
        mine = _is_eng(target)
        report[event] = {
            "installed": mine,
            "foreign_hook_present": not mine,
            "blocking": mine and "--block" in target.read_text(encoding="utf-8", errors="replace"),
            "executable": os.access(target, os.X_OK),
        }
    return report

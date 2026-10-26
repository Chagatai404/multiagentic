"""Install, remove and inspect eng's UserPromptSubmit hook in client settings (M4).

Only entries whose command carries the eng hook module are touched; every other key, hook
and matcher group is preserved. Writes are atomic; an existing file is backed up once to
``<file>.eng-backup`` before its first modification.
"""

import copy
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Any

from eng.core.triggers import TriggerMode, TriggerOrigin
from eng.execution.workspace import git
from eng.integrations.clients import HOOK_MODULE, client_origin, hook_command

EVENT = "UserPromptSubmit"
TIMEOUT_SECONDS = 20
BACKUP_SUFFIX = ".eng-backup"
CODEX_NOTE = (
    "Codex runs this hook only after you trust it: open /hooks in Codex and trust the eng entry."
)


class InstallScope(StrEnum):
    USER = "user"
    PROJECT = "project"


def client_home(origin: TriggerOrigin) -> Path:
    if origin is TriggerOrigin.GEMINI:
        return Path.home() / ".gemini"
    if origin is TriggerOrigin.CURSOR:
        return Path.home() / ".cursor"
    variable, directory = (
        ("CLAUDE_CONFIG_DIR", ".claude")
        if origin is TriggerOrigin.CLAUDE_CODE
        else ("CODEX_HOME", ".codex")
    )
    override = os.environ.get(variable)
    return Path(override).expanduser().resolve() if override else Path.home() / directory


def _settings_path(origin: TriggerOrigin, project_root: Path | None, scope: InstallScope) -> Path:
    if scope is InstallScope.USER:
        filename = (
            "settings.json"
            if origin in {TriggerOrigin.CLAUDE_CODE, TriggerOrigin.GEMINI}
            else "hooks.json"
        )
        return client_home(origin) / filename
    if project_root is None:
        raise ValueError("Project scope requires a project root")
    if origin is TriggerOrigin.CLAUDE_CODE:
        return project_root / ".claude" / "settings.local.json"
    if origin is TriggerOrigin.GEMINI:
        return project_root / ".gemini" / "settings.json"
    if origin is TriggerOrigin.CURSOR:
        return project_root / ".cursor" / "hooks.json"
    return project_root / ".codex" / "hooks.json"


def _entry(origin: TriggerOrigin, argv: list[str]) -> dict[str, Any]:
    if origin is TriggerOrigin.CLAUDE_CODE:
        return {"type": "command", "command": argv[0], "args": argv[1:], "timeout": TIMEOUT_SECONDS}
    if origin in {TriggerOrigin.GEMINI, TriggerOrigin.CURSOR}:
        return {
            "type": "command",
            "command": subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv),
            "timeout": TIMEOUT_SECONDS * 1000
            if origin is TriggerOrigin.GEMINI
            else TIMEOUT_SECONDS,
        }
    return {
        "type": "command",
        "command": shlex.join(argv),
        "commandWindows": subprocess.list2cmdline(argv),
        "timeout": TIMEOUT_SECONDS,
        "statusMessage": "eng: routing prompt",
    }


def _is_eng(hook: Any) -> bool:
    if not isinstance(hook, dict):
        return False
    texts = [hook.get("command"), hook.get("commandWindows"), *(hook.get("args") or [])]
    return any(isinstance(text, str) and HOOK_MODULE in text for text in texts)


def _has_eng(group: Any) -> bool:
    hooks = group.get("hooks") if isinstance(group, dict) else None
    return isinstance(hooks, list) and any(_is_eng(hook) for hook in hooks)


def _mode(hook: dict[str, Any]) -> str | None:
    args = hook.get("args")
    argv = [str(hook.get("command")), *args] if isinstance(args, list) else None
    if argv is None:
        try:
            argv = shlex.split(str(hook.get("command")))
        except ValueError:
            return None
    if "--mode" in argv and argv.index("--mode") + 1 < len(argv):
        return argv[argv.index("--mode") + 1]
    return None


def _load(path: Path) -> tuple[dict[str, Any], bytes | None]:
    if not path.exists():
        return {}, None
    raw = path.read_bytes()
    if not raw.strip():
        return {}, raw
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data, raw


def _event(origin: TriggerOrigin) -> str:
    if origin is TriggerOrigin.GEMINI:
        return "BeforeAgent"
    if origin is TriggerOrigin.CURSOR:
        return "beforeSubmitPrompt"
    return EVENT


def _groups(data: dict[str, Any], event: str = EVENT) -> tuple[dict[str, Any], list[Any]]:
    hooks_map = data.get("hooks", {})
    if not isinstance(hooks_map, dict):
        raise ValueError("settings 'hooks' must be a JSON object")
    groups = hooks_map.get(event, [])
    if not isinstance(groups, list):
        raise ValueError(f"settings 'hooks.{event}' must be a JSON array")
    if event == "beforeSubmitPrompt":
        groups = [{"hooks": [hook]} for hook in groups]
    return hooks_map, groups


def _with_entry(
    data: dict[str, Any], entry: dict[str, Any] | None, event: str = EVENT
) -> dict[str, Any]:
    """Return data with eng hooks replaced by entry (or removed when entry is None)."""
    hooks_map, groups = _groups(data, event)
    if entry is None and not any(_has_eng(group) for group in groups):
        return data

    updated: list[Any] = []
    placed = False
    for group in groups:
        if not _has_eng(group):
            updated.append(group)
            continue
        survivors: list[Any] = []
        for hook in group["hooks"]:
            if not _is_eng(hook):
                survivors.append(hook)
            elif entry is not None and not placed:
                survivors.append(entry)
                placed = True
        if survivors:
            updated.append({**group, "hooks": survivors})
    if entry is not None and not placed:
        updated.append({"hooks": [entry]})

    result = dict(data)
    if updated:
        entries = (
            [hook for group in updated for hook in group["hooks"]]
            if event == "beforeSubmitPrompt"
            else updated
        )
        result["hooks"] = {**hooks_map, event: entries}
        if event == "beforeSubmitPrompt":
            result.setdefault("version", 1)
    else:
        rest = {key: value for key, value in hooks_map.items() if key != event}
        if rest:
            result["hooks"] = rest
        else:
            result.pop("hooks", None)
    return copy.deepcopy(result)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        if path.exists():
            shutil.copymode(path, temp)  # mkstemp is 0600; keep the file's permissions
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def _write(path: Path, raw: bytes | None, data: dict[str, Any]) -> str | None:
    backup: str | None = None
    if raw is not None:
        backup_path = path.with_name(path.name + BACKUP_SUFFIX)
        if not backup_path.exists():
            _atomic_write(backup_path, raw)
            backup = str(backup_path)
    _atomic_write(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return backup


def _exclude_locally(project_root: Path, paths: list[Path]) -> list[str]:
    """Keep eng's per-user hook files out of `git status` via .git/info/exclude.

    Routing requires a clean checkout, so files the installer writes must not dirty it.
    The exclude file is local to this clone and never committed.
    """
    try:
        exclude = Path(git(project_root, "rev-parse", "--git-path", "info/exclude"))
    except ValueError:
        return []  # not a Git repository; nothing to keep clean
    if not exclude.is_absolute():
        exclude = project_root / exclude
    existing = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
    added = []
    for path in paths:
        pattern = "/" + path.relative_to(project_root).as_posix()
        if pattern not in existing:
            added.append(pattern)
    if added:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        prefix = "\n" if existing and existing[-1] != "" else ""
        with exclude.open("a", encoding="utf-8") as handle:
            handle.write(prefix + "\n".join(["# eng prompt hook (local)", *added]) + "\n")
    return added


def install_hook(
    client: str,
    project_root: Path | None = None,
    *,
    mode: str,
    provider: str | None,
    scope: InstallScope = InstallScope.PROJECT,
) -> dict[str, Any]:
    origin = client_origin(client)
    scope = InstallScope(scope)
    binding = project_root if scope is InstallScope.PROJECT else None
    entry = _entry(origin, hook_command(client, mode=mode, provider=provider, project=binding))
    path = _settings_path(origin, project_root, scope)
    if scope is InstallScope.PROJECT and project_root is not None:
        _exclude_locally(project_root, [path, path.with_name(path.name + BACKUP_SUFFIX)])
    data, raw = _load(path)
    updated = _with_entry(data, entry, _event(origin))
    result: dict[str, Any] = {
        "client": origin.value,
        "path": str(path),
        "installed": True,
        "changed": False,
        "backup": None,
        "mode": TriggerMode(mode).value,
    }
    if origin is TriggerOrigin.CODEX:
        result["note"] = CODEX_NOTE
    if updated != data:
        result["changed"] = True
        result["backup"] = _write(path, raw, updated)
    return result


def uninstall_hook(
    client: str, project_root: Path | None = None, *, scope: InstallScope = InstallScope.PROJECT
) -> dict[str, Any]:
    origin = client_origin(client)
    path = _settings_path(origin, project_root, InstallScope(scope))
    data, raw = _load(path)
    updated = _with_entry(data, None, _event(origin))
    result: dict[str, Any] = {
        "client": origin.value,
        "path": str(path),
        "installed": False,
        "changed": False,
        "backup": None,
    }
    if updated != data:
        result["changed"] = True
        result["backup"] = _write(path, raw, updated)
    return result


def hook_status(
    client: str, project_root: Path | None = None, *, scope: InstallScope = InstallScope.PROJECT
) -> dict[str, Any]:
    origin = client_origin(client)
    path = _settings_path(origin, project_root, InstallScope(scope))
    data, _ = _load(path)
    _, groups = _groups(data, _event(origin))
    eng_hooks = [
        hook for group in groups if _has_eng(group) for hook in group["hooks"] if _is_eng(hook)
    ]
    result: dict[str, Any] = {
        "client": origin.value,
        "path": str(path),
        "installed": bool(eng_hooks),
        "entries": len(eng_hooks),
        "mode": _mode(eng_hooks[0]) if eng_hooks else None,
    }
    if origin is TriggerOrigin.CODEX and eng_hooks:
        result["note"] = CODEX_NOTE
    return result

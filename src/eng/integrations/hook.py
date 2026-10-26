"""Client hook entry point: ``python -m eng.integrations.hook CLIENT [--mode M] [--provider P]
[--project PATH]``.

Both supported clients block the user's prompt on exit code 2, so this module never
exits 2: arguments are parsed leniently, every failure (including import errors and
interrupts) fails open with exit 0 and a systemMessage, and stdout is a single JSON
object or nothing. The hook only records the trigger and creates the task; worktrees,
checks and model calls run in a detached ``eng start`` process so the client is never
kept waiting. eng modules are imported lazily so their failures are also fail-open.
"""

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eng.core.triggers import TriggerDecision, TriggerEnvelope, TriggerMode

DEFAULT_PROVIDERS = {
    "claude-code": "claude",
    "codex": "codex",
    "gemini": None,
    "cursor": None,
    "cli": None,
    "ci": None,
}
ACCEPTANCE = [
    "All configured required checks pass",
    "The change does what the routed request asks, without unrelated edits",
]


def runner_argv(task_id: str, project: Path) -> list[str]:
    return [sys.executable, "-m", "eng", "start", task_id, "--project", str(project)]


def submit(
    envelope: "TriggerEnvelope",
    mode: "TriggerMode",
    provider: str | None = None,
    *,
    project: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple["TriggerDecision", Path | None]:
    """Route one trigger: route -> checks -> claim -> create task -> spawn -> started."""
    from eng.core.models import ClassificationOverrides, Complexity, Risk, Task, TaskSpec, now
    from eng.core.triggers import (
        TriggerAction,
        TriggerDecision,
        TriggerRecord,
        idempotency_key,
        prompt_digest,
        route_trigger,
    )
    from eng.execution.workspace import git, repository_root
    from eng.integrations.runner import spawn_detached
    from eng.projects.config import load_config
    from eng.providers.registry import build_registry
    from eng.storage.store import Store

    environment = os.environ if environ is None else environ
    decision = route_trigger(envelope, mode, reentrant=bool(environment.get("ENG_ACTIVE")))
    if decision.action != TriggerAction.ROUTE:
        return decision, None
    assert decision.description is not None
    explicit = envelope.prompt.lstrip().casefold().startswith("eng:")

    def bypass(reason: str) -> tuple[TriggerDecision, Path | None]:
        return TriggerDecision(action=TriggerAction.BYPASS, reason=reason), None

    root = repository_root(Path(envelope.cwd))
    if project is not None and root != project.resolve():
        # A nested repository, submodule or other worktree is not the installed project.
        return bypass("Prompt is outside the project this hook was installed for")
    if project is None and not (root / ".engineering" / "project.yaml").is_file():
        return bypass("Project is not initialized; run eng init and confirm its required checks")
    try:
        git(root, "check-ignore", "--quiet", ".engineering/state/eng.sqlite3")
    except ValueError:
        raise ValueError("eng runtime state is not ignored; run `eng init` and commit it") from None
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        if not explicit:
            return bypass("Uncommitted changes; heuristic routing passes through")
        # The engine would refuse this task, so never block the prompt for it.
        raise ValueError("uncommitted changes; eng routes only from a clean checkout")
    config = load_config(root)
    selected = provider or DEFAULT_PROVIDERS[envelope.origin.value] or config.provider
    # Unknown providers fail before anything is recorded.
    build_registry(command_providers=config.command_providers).create(selected)
    budgets = config.budgets.model_copy(deep=True)
    if decision.full_verification:
        budgets.model_calls = max(budgets.model_calls, 2)  # room for independent review
    if decision.multi_agent:
        budgets.model_calls = max(budgets.model_calls, 3)  # planner, engineer, reviewer
    spec = TaskSpec(
        description=decision.description,
        acceptance=ACCEPTANCE,
        provider=selected,
        budgets=budgets,
        classification_overrides=ClassificationOverrides(
            risk=Risk.MEDIUM if decision.full_verification else None,
            complexity=Complexity.COMPLEX if decision.multi_agent else None,
        ),
    )
    key, content_keyed = idempotency_key(envelope)
    stamp = now()
    record = TriggerRecord(
        key=key,
        origin=envelope.origin,
        session_id=envelope.session_id,
        prompt_digest=prompt_digest(envelope.prompt),
        content_keyed=content_keyed,
        created_at=stamp,
        updated_at=stamp,
    )
    store = Store(root)
    try:
        existing = store.claim_trigger(record, envelope.model_dump(mode="json"), now=stamp)
        if existing is not None:
            if existing.status != "started" or existing.task_id is None:
                # Only a delivery whose runner started may block; failed or interrupted
                # claims never block the prompt without work running for it.
                return bypass("Earlier delivery of this prompt did not start a task")
            return (
                TriggerDecision(
                    action=TriggerAction.DUPLICATE,
                    reason="Trigger already routed",
                    task_id=existing.task_id,
                ),
                root,
            )
        task = Task(project=root, spec=spec, config=config)
        store.create(task)
        store.update_trigger(key, status="claimed", task_id=task.id, now=now())
        log = root / ".engineering" / "artifacts" / task.id / "runner.log"
        try:
            pid = spawn_detached(runner_argv(task.id, root), cwd=root, log_path=log)
        except Exception as error:
            store.update_trigger(
                key, status="failed", task_id=task.id, message=str(error)[:500], now=now()
            )
            raise
        # From here a runner is working: the prompt must be blocked even if bookkeeping fails.
        try:
            store.update_trigger(key, status="started", task_id=task.id, now=now())
            store.event(
                task,
                "trigger_routed",
                {"key": key, "origin": envelope.origin.value, "mode": mode.value, "pid": pid},
            )
            store.artifact(task, log, "runner_log")
        except Exception:  # noqa: BLE001
            pass
        return decision.model_copy(update={"task_id": task.id}), root
    finally:
        store.close()


def _options(arguments: list[str]) -> tuple[str, dict[str, str]]:
    """Lenient parsing: unknown options and missing values are ignored, never fatal."""
    client = ""
    options: dict[str, str] = {}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in {"--mode", "--provider", "--project"} and index + 1 < len(arguments):
            options[argument[2:]] = arguments[index + 1]
            index += 2
            continue
        if not argument.startswith("-") and not client:
            client = argument
        index += 1
    return client, options


def _message(error: BaseException) -> str:
    """Describe a failure without echoing client input (validation errors quote it)."""
    try:
        from pydantic import ValidationError

        from eng.execution.process import redact

        if isinstance(error, ValidationError):
            return "invalid hook input"
        return redact(str(error))[:300] or type(error).__name__
    except Exception:  # noqa: BLE001
        return type(error).__name__


def _run(client: str, options: dict[str, str]) -> str:
    from eng.core.models import now
    from eng.core.triggers import TriggerMode, TriggerOrigin
    from eng.integrations.clients import parse_hook_input, render_decision

    origin = TriggerOrigin(client)
    if origin in {TriggerOrigin.CLI, TriggerOrigin.CI}:
        raise ValueError("Use `eng trigger` or `eng ci-trigger` for non-client triggers")
    mode = TriggerMode(options.get("mode", TriggerMode.MANUAL.value))
    # Clients send UTF-8 regardless of the console code page (e.g. cp1254 on Windows).
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    envelope = parse_hook_input(origin, raw, received_at=now())
    project = Path(options["project"]) if options.get("project") else None
    decision, root = submit(envelope, mode, options.get("provider"), project=project)
    _, output = render_decision(origin, decision, project=root or Path(envelope.cwd))
    return output


def main(arguments: list[str] | None = None) -> int:
    client, options = _options(sys.argv[1:] if arguments is None else arguments)
    try:
        output = _run(client, options)
    except BaseException as error:  # noqa: BLE001 - a hook must never block on its own failure
        # systemMessage is understood by both clients; built without eng imports.
        warning = f"eng hook did not route this prompt: {_message(error)}"
        output = json.dumps(
            {"continue": True, "user_message": warning}
            if client == "cursor"
            else {"systemMessage": warning}
        )
    if output:
        sys.stdout.buffer.write(output.encode("utf-8", errors="replace"))
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

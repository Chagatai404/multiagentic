import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from eng.core.accounting import decimal_cost_total, usage_report
from eng.core.engine import Engine
from eng.core.models import (
    ClassificationOverrides,
    Complexity,
    Risk,
    State,
    Task,
    TaskSpec,
    TaskType,
    now,
)
from eng.core.policy import TERMINAL
from eng.core.triggers import TriggerEnvelope, TriggerMode, TriggerOrigin
from eng.execution.process import redact, redact_data
from eng.execution.workspace import repository_root, task_lock
from eng.integrations.hook import DEFAULT_PROVIDERS, submit
from eng.integrations.install import hook_status, install_hook, uninstall_hook
from eng.projects.config import initialize, load_config
from eng.providers.base import Provider
from eng.providers.registry import build_registry
from eng.storage.store import Store

app = typer.Typer(no_args_is_help=True, help="Execute engineering tasks in isolated Git worktrees.")
hooks_app = typer.Typer(
    no_args_is_help=True,
    help="Install opt-in prompt hooks for Claude Code or Codex in this project only.",
)
app.add_typer(hooks_app, name="hooks")
Project = Annotated[
    Path, typer.Option("--project", "-p", help="Path inside the target Git repository.")
]


def emit(value: object) -> None:
    if isinstance(value, Task):
        value = value.model_dump(mode="json")
    typer.echo(json.dumps(redact_data(value), indent=2, default=str))


def fail(error: Exception) -> NoReturn:
    typer.echo(redact(f"Error: {error}"), err=True)
    raise typer.Exit(2)


def provider_for(name: str, edits: list[str] | None = None) -> Provider:
    if edits and name != "fake":
        raise ValueError("--fake-change is only available with --provider fake")
    changes = {}
    for edit in edits or []:
        path, separator, content = edit.partition("=")
        if not separator or not path:
            raise ValueError("Use --fake-change relative/path=content")
        changes[path] = content
    return build_registry(fake_changes=changes).create(name)


def exit_for(task: Task) -> None:
    emit(task)
    if task.state != State.COMPLETED:
        raise typer.Exit(1)


@app.command()
def init(project: Project = Path(".")) -> None:
    """Propose project.yaml; discovered commands require explicit confirmation."""
    try:
        config = initialize(project)
        emit(
            {
                "configuration": config.model_dump(mode="json"),
                "next": "Review commands, set confirmed: true, then commit the configuration",
            }
        )
    except (ValueError, OSError) as error:
        fail(error)


@app.command()
def run(
    description: str,
    accept: Annotated[
        list[str], typer.Option("--accept", help="Acceptance criterion; repeatable.")
    ],
    project: Project = Path("."),
    provider: Annotated[
        str | None, typer.Option(help="claude, codex or fake; defaults to project config")
    ] = None,
    model: Annotated[
        str | None, typer.Option(help="Explicit provider model, otherwise provider default")
    ] = None,
    context: Annotated[
        list[str] | None, typer.Option(help="Tracked relative context path; repeatable")
    ] = None,
    fake_change: Annotated[
        list[str] | None, typer.Option(help="Fixture edit PATH=CONTENT; fake provider only")
    ] = None,
    wall_seconds: Annotated[
        float | None, typer.Option(min=0.01, help="Total active execution budget")
    ] = None,
    provider_seconds: Annotated[
        float | None, typer.Option(min=0.01, help="Provider invocation timeout")
    ] = None,
    user_config: Annotated[Path | None, typer.Option(help="Optional user defaults YAML")] = None,
    task_type: Annotated[TaskType | None, typer.Option(help="Explicit task type")] = None,
    complexity: Annotated[Complexity | None, typer.Option(help="Minimum task complexity")] = None,
    risk: Annotated[Risk | None, typer.Option(help="Minimum task risk")] = None,
    max_repairs: Annotated[int | None, typer.Option(min=0, max=10)] = None,
    model_calls: Annotated[int | None, typer.Option(min=1, max=100)] = None,
    reported_input_tokens: Annotated[
        int | None, typer.Option(min=1, help="Stop new calls at cumulative reported input tokens")
    ] = None,
    reported_output_tokens: Annotated[
        int | None, typer.Option(min=1, help="Stop new calls at cumulative reported output tokens")
    ] = None,
    reported_cost_usd: Annotated[
        float | None,
        typer.Option(min=0.000001, help="Reported-cost stop threshold; no in-flight cap"),
    ] = None,
    approve_high_risk: Annotated[
        bool, typer.Option(help="Explicitly approve this high-risk task")
    ] = False,
) -> None:
    """Run an adaptive workflow with deterministic checks; print the persisted task."""
    store = None
    try:
        if os.environ.get("ENG_ACTIVE"):
            raise ValueError("Nested eng execution is disabled")
        root = repository_root(project)
        config = load_config(root, user_config)
        budget = config.budgets.model_copy(deep=True)
        if wall_seconds is not None:
            budget.wall_seconds = wall_seconds
        if provider_seconds is not None:
            budget.provider_seconds = provider_seconds
        if model_calls is not None:
            budget.model_calls = model_calls
        if reported_input_tokens is not None:
            budget.reported_input_tokens = reported_input_tokens
        if reported_output_tokens is not None:
            budget.reported_output_tokens = reported_output_tokens
        if reported_cost_usd is not None:
            budget.reported_cost_usd = reported_cost_usd
        if max_repairs is not None:
            config.workflow.max_repairs = max_repairs
        selected = provider_for(provider or config.provider, fake_change)
        spec = TaskSpec(
            description=description,
            acceptance=accept,
            provider=selected.name,
            model=model,
            context_paths=context or [],
            budgets=budget,
            classification_overrides=ClassificationOverrides(
                task_type=task_type,
                complexity=complexity,
                risk=risk,
            ),
            human_approved=approve_high_risk,
        )
        task = Task(project=root, spec=spec, config=config)
        store = Store(root)
        store.create(task)
        exit_for(asyncio.run(Engine(store, selected).execute(task.id)))
    except (ValueError, OSError, ValidationError) as error:
        fail(error)
    finally:
        if store is not None:
            store.close()


@app.command()
def status(
    task_id: Annotated[str | None, typer.Argument()] = None,
    project: Project = Path("."),
) -> None:
    """Inspect a task across processes, or list all project tasks."""
    store = None
    try:
        store = Store(repository_root(project))
        if task_id:
            task = store.load(task_id)
            emit({"task": task.model_dump(mode="json"), "events": store.events(task_id)})
        else:
            emit(
                [
                    {"id": task.id, "state": task.state, "message": task.message}
                    for task in store.list_tasks()
                ]
            )
    except (ValueError, OSError) as error:
        fail(error)
    finally:
        if store is not None:
            store.close()


def continue_task(
    task_id: str,
    project: Path,
    verify_only: bool,
    extend_seconds: float,
    extend_model_calls: int = 0,
    approve_high_risk: bool = False,
    extend_input_tokens: int = 0,
    extend_output_tokens: int = 0,
    extend_cost_usd: float = 0,
    clear_reported_limits: bool = False,
) -> None:
    store = None
    try:
        root = repository_root(project)
        store = Store(root)
        if (
            extend_seconds
            or extend_model_calls
            or approve_high_risk
            or extend_input_tokens
            or extend_output_tokens
            or extend_cost_usd
            or clear_reported_limits
        ):
            with task_lock(root, task_id):
                task = store.load(task_id)
                if task.state in TERMINAL:
                    raise ValueError("Cannot extend a terminal task")
                if clear_reported_limits and (
                    extend_input_tokens or extend_output_tokens or extend_cost_usd
                ):
                    raise ValueError("Clear reported limits and extensions are mutually exclusive")
                for field, extension in (
                    ("reported_input_tokens", extend_input_tokens),
                    ("reported_output_tokens", extend_output_tokens),
                    ("reported_cost_usd", extend_cost_usd),
                ):
                    current = getattr(task.spec.budgets, field)
                    if extension:
                        if current is None:
                            raise ValueError(f"Cannot extend an unset {field} limit")
                        total = (
                            float(decimal_cost_total([current, extension]))
                            if field == "reported_cost_usd"
                            else current + extension
                        )
                        setattr(task.spec.budgets, field, total)
                    if clear_reported_limits:
                        setattr(task.spec.budgets, field, None)
                task.spec.budgets.wall_seconds += extend_seconds
                task.spec.budgets.model_calls += extend_model_calls
                if approve_high_risk:
                    task.spec.human_approved = True
                    store.event(task, "human_approved", {"source": "explicit_cli"})
                store.checkpoint(task)
                store.event(
                    task,
                    "budget_extended",
                    {
                        "seconds": extend_seconds,
                        "model_calls": extend_model_calls,
                        "input_tokens": extend_input_tokens,
                        "output_tokens": extend_output_tokens,
                        "cost_usd": extend_cost_usd,
                        "reported_limits_cleared": clear_reported_limits,
                    },
                )
        task = store.load(task_id)
        selected = provider_for(task.spec.provider)
        exit_for(
            asyncio.run(
                Engine(store, selected).execute(task_id, resume=True, verify_only=verify_only)
            )
        )
    except (ValueError, OSError) as error:
        fail(error)
    finally:
        if store is not None:
            store.close()


@app.command()
def resume(
    task_id: str,
    project: Project = Path("."),
    verify_only: Annotated[
        bool, typer.Option(help="Acknowledge unknown outcome and run checks only")
    ] = False,
    extend_seconds: Annotated[
        float, typer.Option(min=0, help="Explicitly add active wall time")
    ] = 0,
    extend_model_calls: Annotated[
        int, typer.Option(min=0, max=99, help="Explicitly add model calls")
    ] = 0,
    approve_high_risk: Annotated[
        bool, typer.Option(help="Explicitly approve the saved high-risk task")
    ] = False,
    extend_input_tokens: Annotated[int, typer.Option(min=0)] = 0,
    extend_output_tokens: Annotated[int, typer.Option(min=0)] = 0,
    extend_cost_usd: Annotated[float, typer.Option(min=0)] = 0,
    clear_reported_limits: Annotated[
        bool,
        typer.Option(help="Explicitly remove reported limits, including unknown-coverage stops"),
    ] = False,
) -> None:
    """Continue a safe checkpoint; uncertain provider work requires --verify-only."""
    continue_task(
        task_id,
        project,
        verify_only,
        extend_seconds,
        extend_model_calls,
        approve_high_risk,
        extend_input_tokens,
        extend_output_tokens,
        extend_cost_usd,
        clear_reported_limits,
    )


@app.command()
def usage(task_id: str, project: Project = Path(".")) -> None:
    """Report native usage and missing coverage across every task execution."""
    store = None
    try:
        store = Store(repository_root(project))
        task = store.load(task_id)
        report = usage_report(store.invocations(task_id), task.config.pricing)
        emit({"task_id": task_id, **report.model_dump(mode="json")})
    except (ValueError, OSError) as error:
        fail(error)
    finally:
        if store is not None:
            store.close()


@app.command()
def benchmark(
    repetitions: Annotated[int, typer.Option(min=1, max=10)] = 1,
    seed: Annotated[int, typer.Option(min=0, max=4294967295)] = 0,
    scenario: Annotated[list[str] | None, typer.Option(help="Repeatable scenario name")] = None,
) -> None:
    """Run offline scripted fixtures; no paid models or real-model quality claims."""
    from eng.benchmark import run_benchmark

    try:
        emit(run_benchmark(repetitions=repetitions, seed=seed, scenarios=scenario))
    except (ValueError, OSError) as error:
        fail(error)


@app.command()
def verify(task_id: str, project: Project = Path(".")) -> None:
    """Rerun saved checks for interrupted or blocked tasks without invoking a model."""
    continue_task(task_id, project, True, 0)


@app.command()
def cancel(task_id: str, project: Project = Path(".")) -> None:
    """Persist cancellation; active runners stop their process tree and retain changes."""
    store = None
    try:
        root = repository_root(project)
        store = Store(root)
        requested = store.cancel(task_id)
        if requested:
            try:
                with task_lock(root, task_id):
                    task = store.load(task_id)
                    if task.state not in TERMINAL:
                        store.transition(
                            task, State.CANCELLED, "Cancelled while idle; workspace retained"
                        )
            except ValueError:
                pass  # The active owner will acknowledge the durable request.
        emit(
            {
                "task_id": task_id,
                "cancellation_requested": requested,
                "state": store.load(task_id).state,
            }
        )
    except (ValueError, OSError) as error:
        fail(error)
    finally:
        if store is not None:
            store.close()


@app.command()
def start(task_id: str, project: Project = Path(".")) -> None:
    """Execute a CREATED task, e.g. one queued by a client hook's detached runner."""
    store = None
    try:
        if os.environ.get("ENG_ACTIVE"):
            raise ValueError("Nested eng execution is disabled")
        store = Store(repository_root(project))
        task = store.load(task_id)
        if task.state != State.CREATED:
            raise ValueError("Task already started; use resume or status")
        selected = provider_for(task.spec.provider)
        exit_for(asyncio.run(Engine(store, selected).execute(task_id)))
    except (ValueError, OSError) as error:
        fail(error)
    finally:
        if store is not None:
            store.close()


@app.command()
def trigger(
    prompt: str,
    project: Project = Path("."),
    mode: Annotated[TriggerMode, typer.Option(help="Routing mode")] = TriggerMode.MANUAL,
    provider: Annotated[
        str | None, typer.Option(help="Provider for routed work; defaults to project config")
    ] = None,
    session: Annotated[str | None, typer.Option(help="Caller session identity")] = None,
    turn: Annotated[str | None, typer.Option(help="Caller turn id for idempotency")] = None,
) -> None:
    """Submit a normalized trigger; routed work runs in a detached `eng start` process."""
    try:
        envelope = TriggerEnvelope(
            origin=TriggerOrigin.CLI,
            session_id=session,
            turn_id=turn,
            cwd=str(project.resolve()),
            prompt=prompt,
            received_at=now(),
        )
        decision, _ = submit(envelope, mode, provider)
        emit(decision.model_dump(mode="json"))
    except (ValueError, OSError, ValidationError) as error:
        fail(error)


@app.command()
def triggers(project: Project = Path("."), limit: int = 50) -> None:
    """List recent trigger records (digests and status, never raw prompts)."""
    store = None
    try:
        store = Store(repository_root(project))
        emit([record.model_dump(mode="json") for record in store.triggers(limit)])
    except (ValueError, OSError) as error:
        fail(error)
    finally:
        if store is not None:
            store.close()


Client = Annotated[TriggerOrigin, typer.Argument(help="claude-code or codex")]


def hook_client(client: TriggerOrigin) -> str:
    if client == TriggerOrigin.CLI:
        raise ValueError("Hooks are installed for claude-code or codex")
    return client.value


@hooks_app.command("install")
def hooks_install(
    client: Client,
    project: Project = Path("."),
    mode: Annotated[TriggerMode, typer.Option(help="Routing mode")] = TriggerMode.MANUAL,
    provider: Annotated[
        str | None, typer.Option(help="Provider for routed work; defaults to the client's")
    ] = None,
) -> None:
    """Add or update this project's local eng prompt hook; other hooks are preserved."""
    try:
        name = hook_client(client)
        selected = provider or DEFAULT_PROVIDERS[client] or "codex"
        build_registry().create(selected)
        emit(install_hook(name, repository_root(project), mode=mode.value, provider=selected))
    except (ValueError, OSError) as error:
        fail(error)


@hooks_app.command("uninstall")
def hooks_uninstall(client: Client, project: Project = Path(".")) -> None:
    """Remove only eng's prompt hook entries from this project's client settings."""
    try:
        emit(uninstall_hook(hook_client(client), repository_root(project)))
    except (ValueError, OSError) as error:
        fail(error)


@hooks_app.command("status")
def hooks_status(client: Client, project: Project = Path(".")) -> None:
    """Show whether this project's client settings contain the eng prompt hook."""
    try:
        emit(hook_status(hook_client(client), repository_root(project)))
    except (ValueError, OSError) as error:
        fail(error)


@app.command()
def providers() -> None:
    """Show implemented adapters and their declared capabilities."""
    emit(
        {
            name: capabilities.model_dump(mode="json")
            for name, capabilities in build_registry().capabilities().items()
        }
    )


@app.command()
def doctor() -> None:
    """Check executable versions; authentication and model access are not checked."""
    result: dict[str, object] = {"git": shutil.which("git")}
    result.update(asyncio.run(build_registry().doctor(Path.cwd())))
    emit(result)

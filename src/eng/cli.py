import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from eng.core.engine import Engine
from eng.core.models import State, Task, TaskSpec
from eng.core.policy import TERMINAL
from eng.execution.process import redact, redact_data
from eng.execution.workspace import repository_root, task_lock
from eng.projects.config import initialize, load_config
from eng.providers.base import Provider
from eng.providers.registry import build_registry
from eng.storage.store import Store

app = typer.Typer(no_args_is_help=True, help="Execute engineering tasks in isolated Git worktrees.")
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
) -> None:
    """Run one engineer and deterministic checks; print the persisted task as JSON."""
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
        selected = provider_for(provider or config.provider, fake_change)
        spec = TaskSpec(
            description=description,
            acceptance=accept,
            provider=selected.name,
            model=model,
            context_paths=context or [],
            budgets=budget,
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


def continue_task(task_id: str, project: Path, verify_only: bool, extend_seconds: float) -> None:
    store = None
    try:
        root = repository_root(project)
        store = Store(root)
        if extend_seconds:
            with task_lock(root, task_id):
                task = store.load(task_id)
                if task.state in TERMINAL:
                    raise ValueError("Cannot extend a terminal task")
                task.spec.budgets.wall_seconds += extend_seconds
                store.checkpoint(task)
                store.event(task, "budget_extended", {"seconds": extend_seconds})
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
) -> None:
    """Continue a safe checkpoint; uncertain provider work requires --verify-only."""
    continue_task(task_id, project, verify_only, extend_seconds)


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

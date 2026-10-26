import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Annotated, NoReturn

import typer
import yaml
from pydantic import BaseModel, ValidationError

from eng import __version__
from eng.core.accounting import decimal_cost_total, usage_report
from eng.core.engine import Engine
from eng.core.models import (
    ClassificationOverrides,
    CommandProviderConfig,
    Complexity,
    ProjectConfig,
    Risk,
    State,
    Task,
    TaskSpec,
    TaskType,
    now,
)
from eng.core.plan import PlanSpec, PlanStatus, topological_order
from eng.core.policy import TERMINAL
from eng.core.refs import CIConclusion, CIEvent, ci_bypass, ci_description, ci_idempotency
from eng.core.triggers import TriggerEnvelope, TriggerMode, TriggerOrigin
from eng.execution.process import redact, redact_data
from eng.execution.workspace import repository_root, task_lock
from eng.integrations import gitinstall
from eng.integrations.gitref import verify_ref
from eng.integrations.hook import DEFAULT_PROVIDERS, submit
from eng.integrations.install import hook_status, install_hook, uninstall_hook
from eng.projects.config import initialize, load_config
from eng.providers.base import Provider
from eng.providers.registry import build_registry
from eng.scheduling.integration import promote
from eng.scheduling.runner import PlanRunner
from eng.storage.store import Store

app = typer.Typer(no_args_is_help=True, help="Execute engineering tasks in isolated Git worktrees.")
hooks_app = typer.Typer(
    no_args_is_help=True,
    help="Install opt-in prompt hooks for Claude Code or Codex in this project only.",
)
app.add_typer(hooks_app, name="hooks")
git_hooks_app = typer.Typer(
    no_args_is_help=True,
    help="Opt-in Git hooks (post-commit, pre-push) that verify commits; never overwrite yours.",
)
hooks_app.add_typer(git_hooks_app, name="git")
mcp_app = typer.Typer(no_args_is_help=True, help="Optional MCP server exposing eng state.")
app.add_typer(mcp_app, name="mcp")
plan_app = typer.Typer(
    no_args_is_help=True,
    help="Dependency-scheduled parallel plans with verified integration and gated promotion.",
)
app.add_typer(plan_app, name="plan")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"eng {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=version_callback, is_eager=True, help="Show version"),
    ] = False,
) -> None:
    """Execute engineering tasks in isolated Git worktrees."""


Project = Annotated[
    Path, typer.Option("--project", "-p", help="Path inside the target Git repository.")
]


def emit(value: object) -> None:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    typer.echo(json.dumps(redact_data(value), indent=2, default=str))


def fail(error: Exception) -> NoReturn:
    typer.echo(redact(f"Error: {error}"), err=True)
    raise typer.Exit(2)


def provider_for(
    name: str,
    edits: list[str] | None = None,
    config: ProjectConfig | None = None,
) -> Provider:
    if edits and name != "fake":
        raise ValueError("--fake-change is only available with --provider fake")
    changes = {}
    for edit in edits or []:
        path, separator, content = edit.partition("=")
        if not separator or not path:
            raise ValueError("Use --fake-change relative/path=content")
        changes[path] = content
    commands: dict[str, CommandProviderConfig] = config.command_providers if config else {}
    return build_registry(fake_changes=changes, command_providers=commands).create(name)


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
        selected = provider_for(provider or config.provider, fake_change, config)
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
        selected = provider_for(task.spec.provider, None, task.config)
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
        selected = provider_for(task.spec.provider, None, task.config)
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
    if client in {TriggerOrigin.CLI, TriggerOrigin.CI}:
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


def project_commands(project: Path | None) -> dict[str, CommandProviderConfig]:
    """Command providers from the project's configuration, when run inside a project."""
    try:
        return load_config(repository_root(project or Path("."))).command_providers
    except (ValueError, OSError):
        return {}


@mcp_app.command("serve")
def mcp_serve(
    project: Project = Path("."),
    allow_submit: Annotated[
        bool, typer.Option(help="Also expose eng_submit (starts one task; may be billable)")
    ] = False,
) -> None:
    """Serve MCP over stdio for one project: read-only tools; approvals stay human-only."""
    from eng.integrations.mcp import McpServer, serve_stdio

    try:
        server = McpServer(repository_root(project), allow_submit=allow_submit)
    except (ValueError, OSError) as error:
        fail(error)
    serve_stdio(server)


@app.command("verify-ref")
def verify_ref_command(
    rev: Annotated[str, typer.Argument(help="Commit, branch or tag to verify")] = "HEAD",
    project: Project = Path("."),
    origin: Annotated[str, typer.Option(help="Recorded source: manual, post-commit, pre-push")] = (
        "manual"
    ),
) -> None:
    """Verify a commit in a throwaway worktree with the project's confirmed checks."""
    store = None
    try:
        root = repository_root(project)
        store = Store(root)
        record = verify_ref(store, root, rev, load_config(root), origin=origin)
        emit(record)
        if record.status != "PASS":
            raise typer.Exit(1)
    except (ValueError, OSError) as error:
        fail(error)
    finally:
        if store is not None:
            store.close()


@app.command()
def refs(project: Project = Path("."), limit: int = 20) -> None:
    """List recent commit verifications recorded by hooks and `verify-ref`."""
    store = None
    try:
        store = Store(repository_root(project))
        emit(
            [
                {
                    "id": c.id,
                    "rev": c.rev,
                    "commit": c.commit,
                    "origin": c.origin,
                    "status": c.status,
                    "message": c.message,
                    "created_at": c.created_at,
                }
                for c in store.ref_checks(limit)
            ]
        )
    except (ValueError, OSError) as error:
        fail(error)
    finally:
        if store is not None:
            store.close()


@app.command("ci-trigger")
def ci_trigger(
    project: Project = Path("."),
    conclusion: Annotated[CIConclusion, typer.Option(help="CI run conclusion")] = (
        CIConclusion.FAILURE
    ),
    workflow: Annotated[str | None, typer.Option(help="Workflow/pipeline name")] = None,
    run_id: Annotated[str | None, typer.Option(help="CI run id (idempotency key)")] = None,
    attempt: Annotated[int | None, typer.Option(min=1, help="Run attempt")] = None,
    ref: Annotated[str | None, typer.Option(help="Branch or tag the run built")] = None,
    commit: Annotated[str | None, typer.Option(help="Commit the run built")] = None,
    summary: Annotated[str, typer.Option(help="Failure summary (untrusted CI output)")] = "",
    summary_file: Annotated[Path | None, typer.Option(help="Read the summary from a file")] = None,
    ci: Annotated[str, typer.Option(help="CI system name")] = "ci",
    from_github_env: Annotated[
        bool, typer.Option(help="Fill unset fields from GITHUB_* environment variables")
    ] = False,
    mode: Annotated[TriggerMode, typer.Option(help="Routing mode")] = TriggerMode.MANUAL,
    provider: Annotated[
        str | None, typer.Option(help="Provider for the repair task; defaults to project config")
    ] = None,
) -> None:
    """Turn a failing CI run into one repair task (deduplicated by run id and attempt).

    Successful, cancelled or skipped runs do nothing. Routed work runs in a detached
    `eng start` process like every other trigger; nothing is pushed or merged.
    """
    try:
        env = os.environ if from_github_env else {}
        if from_github_env:
            ci = "github"
        text = summary
        if summary_file is not None:
            if summary_file.stat().st_size > 5_000_000:
                raise ValueError("Summary file too large")
            text = summary_file.read_text(encoding="utf-8", errors="replace")[-8000:]
        event = CIEvent(
            ci=ci,
            workflow=workflow or env.get("GITHUB_WORKFLOW") or "unknown",
            run_id=run_id or env.get("GITHUB_RUN_ID") or "",
            attempt=attempt or int(env.get("GITHUB_RUN_ATTEMPT") or 1),
            conclusion=conclusion,
            ref=ref or env.get("GITHUB_REF_NAME"),
            commit=commit or env.get("GITHUB_SHA"),
            summary=redact(text)[-8000:],
        )
        bypass = ci_bypass(event)
        if bypass is not None:
            emit(bypass.model_dump(mode="json"))
            return
        envelope = TriggerEnvelope(
            origin=TriggerOrigin.CI,
            session_id=event.ci,
            turn_id=ci_idempotency(event),
            cwd=str(project.resolve()),
            prompt="eng: " + ci_description(event),
            received_at=now(),
        )
        decision, _ = submit(envelope, mode, provider)
        emit(decision.model_dump(mode="json"))
    except (ValueError, OSError, ValidationError) as error:
        fail(error)


@git_hooks_app.command("install")
def git_hooks_install(
    project: Project = Path("."),
    event: Annotated[
        list[str] | None, typer.Option(help="post-commit and/or pre-push; default both")
    ] = None,
    block: Annotated[
        bool, typer.Option(help="pre-push waits for verification and blocks on a definitive FAIL")
    ] = False,
) -> None:
    """Install verification hooks; refuses to touch a hook eng did not write."""
    try:
        emit(
            gitinstall.install(
                repository_root(project), event or list(gitinstall.EVENTS), block=block
            )
        )
    except (ValueError, OSError) as error:
        fail(error)


@git_hooks_app.command("uninstall")
def git_hooks_uninstall(project: Project = Path(".")) -> None:
    """Remove only eng-managed Git hooks."""
    try:
        emit(gitinstall.uninstall(repository_root(project)))
    except (ValueError, OSError) as error:
        fail(error)


@git_hooks_app.command("status")
def git_hooks_status(project: Project = Path(".")) -> None:
    """Show which Git hooks are eng-managed."""
    try:
        emit(gitinstall.status(repository_root(project)))
    except (ValueError, OSError) as error:
        fail(error)


@app.command()
def providers(
    project: Annotated[
        Path | None, typer.Option("--project", "-p", help="Include its command providers")
    ] = None,
) -> None:
    """Show implemented adapters and their declared capabilities."""
    registry = build_registry(command_providers=project_commands(project))
    emit({name: caps.model_dump(mode="json") for name, caps in registry.capabilities().items()})


@app.command()
def doctor(
    project: Annotated[
        Path | None, typer.Option("--project", "-p", help="Include its command providers")
    ] = None,
) -> None:
    """Check executable versions; authentication and model access are not checked."""
    result: dict[str, object] = {"git": shutil.which("git")}
    registry = build_registry(command_providers=project_commands(project))
    result.update(asyncio.run(registry.doctor(Path.cwd())))
    emit(result)


def load_plan_spec(path: Path) -> PlanSpec:
    if path.stat().st_size > 1_000_000:
        raise ValueError(f"Plan file too large: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))  # JSON is valid YAML
    if not isinstance(document, dict):
        raise ValueError("A plan file must contain a mapping")
    return PlanSpec.model_validate(document)


def plan_runner(root: Path, config: ProjectConfig) -> PlanRunner:
    return PlanRunner(root, lambda name, cfg: provider_for(name, None, cfg or config))


def exit_for_plan(plan: BaseModel, ok: bool) -> None:
    emit(plan)
    if not ok:
        raise typer.Exit(1)


@plan_app.command("validate")
def plan_validate(file: Path) -> None:
    """Validate a plan file (graph, ownership overlap, concurrency) without side effects."""
    try:
        spec = load_plan_spec(file)
        emit(
            {
                "valid": True,
                "name": spec.name,
                "order": topological_order(spec),
                "concurrency": spec.concurrency,
            }
        )
    except (ValueError, OSError, ValidationError, yaml.YAMLError) as error:
        fail(error)


@plan_app.command("create")
def plan_create(file: Path, project: Project = Path(".")) -> None:
    """Create a plan: eng-owned integration branch and worktree; no model runs yet."""
    store = None
    try:
        root = repository_root(project)
        config = load_config(root)
        store = Store(root)
        emit(plan_runner(root, config).create(store, load_plan_spec(file), config))
    except (ValueError, OSError, ValidationError, yaml.YAMLError) as error:
        fail(error)
    finally:
        if store is not None:
            store.close()


def run_plan_command(
    plan_id: str,
    project: Path,
    keep_going: bool,
    approve_high_risk: bool,
    resume: bool,
    clear_limits: bool = False,
) -> None:
    try:
        if os.environ.get("ENG_ACTIVE"):
            raise ValueError("Nested eng execution is disabled")
        root = repository_root(project)
        plan = plan_runner(root, load_config(root)).run(
            plan_id,
            keep_going=keep_going,
            approve_high_risk=approve_high_risk,
            resume=resume,
            clear_limits=clear_limits,
        )
        exit_for_plan(plan, plan.status == PlanStatus.READY)
    except (ValueError, OSError) as error:
        fail(error)


KeepGoing = Annotated[
    bool, typer.Option(help="Keep launching independent nodes after a node fails or pauses")
]
ApproveAll = Annotated[
    bool, typer.Option(help="Explicitly approve every high-risk node task in this run")
]


@plan_app.command("run")
def plan_run(
    plan_id: str,
    project: Project = Path("."),
    keep_going: KeepGoing = False,
    approve_high_risk: ApproveAll = False,
) -> None:
    """Schedule ready nodes (max three at once), integrate verified results, until idle."""
    run_plan_command(plan_id, project, keep_going, approve_high_risk, False)


@plan_app.command("resume")
def plan_resume(
    plan_id: str,
    project: Project = Path("."),
    keep_going: KeepGoing = False,
    approve_high_risk: ApproveAll = False,
    clear_limits: Annotated[
        bool, typer.Option(help="Explicitly remove plan-wide reported-usage limits")
    ] = False,
) -> None:
    """Continue after pauses/blocks: relaunch paused nodes and retry blocked integrations."""
    run_plan_command(plan_id, project, keep_going, approve_high_risk, True, clear_limits)


@plan_app.command("status")
def plan_status(
    plan_id: Annotated[str | None, typer.Argument()] = None, project: Project = Path(".")
) -> None:
    """Inspect a plan across processes, or list the project's plans."""
    store = None
    try:
        store = Store(repository_root(project))
        if plan_id is None:
            emit(
                [
                    {"id": p.id, "name": p.spec.name, "status": p.status, "message": p.message}
                    for p in store.list_plans()
                ]
            )
        else:
            emit(
                {
                    "plan": store.load_plan(plan_id).model_dump(mode="json"),
                    "events": store.plan_events(plan_id),
                }
            )
    except (ValueError, OSError) as error:
        fail(error)
    finally:
        if store is not None:
            store.close()


@plan_app.command("approve")
def plan_approve(plan_id: str, node: str, project: Project = Path(".")) -> None:
    """Explicitly approve one high-risk node's task; then `plan resume`."""
    store = None
    try:
        root = repository_root(project)
        store = Store(root)
        emit(plan_runner(root, load_config(root)).approve_node(store, plan_id, node))
    except (ValueError, OSError) as error:
        fail(error)
    finally:
        if store is not None:
            store.close()


@plan_app.command("cancel")
def plan_cancel(plan_id: str, project: Project = Path(".")) -> None:
    """Persist cancellation; running nodes stop and every workspace is retained."""
    store = None
    try:
        root = repository_root(project)
        store = Store(root)
        emit(plan_runner(root, load_config(root)).cancel(store, plan_id))
    except (ValueError, OSError) as error:
        fail(error)
    finally:
        if store is not None:
            store.close()


@plan_app.command("usage")
def plan_usage(plan_id: str, project: Project = Path(".")) -> None:
    """Report native usage and coverage across every node task of the plan."""
    store = None
    try:
        root = repository_root(project)
        store = Store(root)
        plan = store.load_plan(plan_id)
        records = [r for n in plan.nodes if n.task_id for r in store.invocations(n.task_id)]
        report = usage_report(records, load_config(root).pricing)
        emit({"plan_id": plan_id, **report.model_dump(mode="json")})
    except (ValueError, OSError) as error:
        fail(error)
    finally:
        if store is not None:
            store.close()


@plan_app.command("promote")
def plan_promote(
    plan_id: str,
    project: Project = Path("."),
    approve: Annotated[
        bool, typer.Option(help="Explicit approval to fast-forward the current branch")
    ] = False,
) -> None:
    """Report promotion readiness; with --approve fast-forward the checked-out branch.

    Never pushes. Refuses unless every node is integrated and verified, the checkout is
    clean on a branch, and the move is a pure fast-forward to the verified head.
    """
    store = None
    try:
        root = repository_root(project)
        store = Store(root)
        with task_lock(root, f"plan-{plan_id}"):
            report = promote(store, store.load_plan(plan_id), approved=approve)
        emit(report)
        if not report["promotable"] or (approve and not report["promoted"]):
            raise typer.Exit(1)
    except (ValueError, OSError) as error:
        fail(error)
    finally:
        if store is not None:
            store.close()

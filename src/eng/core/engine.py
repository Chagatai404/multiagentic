import asyncio
import time

from eng.context.packet import build_packet
from eng.core.models import ProviderRequest, State, Task, identity
from eng.core.policy import TERMINAL, completion_gate
from eng.execution.process import redact
from eng.execution.workspace import (
    changed_paths,
    git,
    prepare,
    protected_changes,
    save_diff,
    task_lock,
)
from eng.providers.base import Provider
from eng.storage.store import Store
from eng.verification.runner import run_checks


class Engine:
    """Sequential M1 shell. Dependencies enter through the constructor."""

    def __init__(self, store: Store, provider: Provider) -> None:
        self.store = store
        self.provider = provider

    async def execute(
        self, task_id: str, *, resume: bool = False, verify_only: bool = False
    ) -> Task:
        initial = self.store.load(task_id)
        with task_lock(initial.project, task_id):
            task = self.store.load(task_id)
            if task.state in TERMINAL:
                raise ValueError(f"Task is terminal ({task.state}); submit a new task")
            if task.spec.provider != self.provider.name:
                raise ValueError("Provider does not match the saved task")
            if task.state != State.CREATED and not resume:
                raise ValueError("Use resume for an existing task")
            if verify_only and task.checkpoint not in {
                "provider_started",
                "implemented",
                "verified",
            }:
                raise ValueError("Task has no implementation to verify")
            task.execution_id = identity()
            self.store.start_execution(task)
            directory = task.project / ".engineering" / "artifacts" / task.id / task.execution_id
            directory.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            previous_elapsed = task.elapsed_seconds

            def remaining() -> float:
                return (
                    task.spec.budgets.wall_seconds - previous_elapsed - (time.monotonic() - started)
                )

            def cancelled() -> bool:
                return self.store.cancelled(task.id)

            try:
                if cancelled():
                    self.store.transition(task, State.CANCELLED, "Cancellation acknowledged")
                    return task
                if remaining() <= 0:
                    message = "Wall-clock budget exhausted; extend explicitly"
                    if task.state != State.PAUSED:
                        self.store.transition(task, State.PAUSED, message)
                    else:
                        task.message = message
                    return task
                if resume:
                    if task.state not in {State.PAUSED, State.BLOCKED}:
                        self.store.transition(task, State.PAUSED, "Recovered interrupted execution")
                    if task.checkpoint == "provider_started" and not verify_only:
                        if task.state != State.PAUSED:
                            self.store.transition(task, State.PAUSED, "Provider outcome unknown")
                        task.message = (
                            "Provider outcome unknown; inspect workspace, then resume --verify-only"
                        )
                        return task
                    if verify_only or task.checkpoint in {"implemented", "verified"}:
                        self._validate_workspace(task)
                        task.checkpoint = "implemented"
                        self.store.checkpoint(task)
                        self.store.transition(
                            task, State.VERIFYING, "Continue from implementation checkpoint"
                        )
                    elif task.checkpoint == "prepared":
                        self._validate_workspace(task)
                        self.store.transition(task, State.PREPARING_CONTEXT)
                    else:
                        self.store.transition(task, State.CLASSIFYING)
                else:
                    self.store.transition(task, State.CLASSIFYING)
                if task.state == State.CLASSIFYING:
                    # M1 intentionally uses one workflow. Adaptive decisions arrive in M3.
                    self.store.event(task, "workflow", {"name": "sequential", "role": "engineer"})
                    self.store.transition(task, State.PREPARING_CONTEXT)
                if task.state == State.PREPARING_CONTEXT:
                    if task.workspace is None:
                        prepare(task)
                        task.checkpoint = "prepared"
                        self.store.checkpoint(task)
                    if not self.provider.capabilities.file_editing:
                        raise ValueError("Provider does not support file editing")
                    if task.provider_calls >= task.spec.budgets.model_calls:
                        self.store.transition(task, State.PAUSED, "Model-call budget exhausted")
                        return task
                    context_started = time.monotonic()
                    prompt = build_packet(task)
                    self.store.event(
                        task,
                        "context",
                        {
                            "chars": len(prompt),
                            "duration_seconds": time.monotonic() - context_started,
                        },
                    )
                    if remaining() <= 0:
                        self.store.transition(task, State.PAUSED, "Wall-clock budget exhausted")
                        return task
                    self.store.transition(task, State.IMPLEMENTING)
                    task.checkpoint = "provider_started"
                    task.provider_calls += 1
                    self.store.checkpoint(task)  # committed BEFORE the side effect
                    assert task.workspace is not None
                    result = await self.provider.execute(
                        ProviderRequest(
                            task_id=task.id,
                            execution_id=task.execution_id,
                            workspace=task.workspace,
                            prompt=prompt,
                            model=task.spec.model,
                            timeout_seconds=min(task.spec.budgets.provider_seconds, remaining()),
                        ),
                        directory,
                        cancelled,
                    )
                    self.store.invocation(task, result.model_dump_json())
                    task.usage = result.usage
                    if cancelled() or result.status == "cancelled":
                        self.store.transition(
                            task, State.CANCELLED, "Provider stopped; workspace preserved"
                        )
                        return task
                    if result.status == "timeout":
                        self.store.transition(
                            task,
                            State.PAUSED,
                            "Provider timed out; inspect outcome before verification",
                        )
                        return task
                    if result.status != "success":
                        self.store.transition(
                            task, State.FAILED, f"{result.error_kind}: {result.summary}"
                        )
                        return task
                    task.checkpoint = "implemented"
                    self.store.checkpoint(task)
                    self.store.transition(task, State.VERIFYING)
                if task.state == State.VERIFYING:
                    self._validate_workspace(task)
                    assert task.workspace is not None
                    paths = changed_paths(task.workspace, task.base_commit or "HEAD")
                    forbidden = protected_changes(paths, task.config.protected_paths)
                    if forbidden:
                        self.store.transition(
                            task, State.FAILED, "Protected files changed: " + ", ".join(forbidden)
                        )
                        return task
                    task.verification = await run_checks(
                        task.workspace,
                        task.config.checks,
                        directory / "checks",
                        cancelled,
                        remaining(),
                    )
                    self.store.verification(task)
                    # Checks are project code and may mutate files; recheck protection afterward.
                    self._validate_workspace(task)
                    forbidden = protected_changes(
                        changed_paths(task.workspace, task.base_commit or "HEAD"),
                        task.config.protected_paths,
                    )
                    if cancelled():
                        self.store.transition(
                            task, State.CANCELLED, "Verification cancelled; workspace preserved"
                        )
                    elif forbidden:
                        self.store.transition(
                            task,
                            State.FAILED,
                            "Checks modified protected files: " + ", ".join(forbidden),
                        )
                    elif remaining() <= 0:
                        self.store.transition(
                            task, State.PAUSED, "Wall-clock budget exhausted during verification"
                        )
                    else:
                        accepted, reason = completion_gate(task.verification)
                        task.checkpoint = "verified"
                        self.store.checkpoint(task)
                        self.store.transition(
                            task, State.COMPLETED if accepted else State.BLOCKED, reason
                        )
            except (KeyboardInterrupt, asyncio.CancelledError):
                if task.state not in TERMINAL:
                    self.store.transition(
                        task, State.PAUSED, "Execution interrupted; workspace preserved"
                    )
            except Exception as error:
                if task.state not in TERMINAL:
                    self.store.transition(task, State.FAILED, redact(str(error)))
            finally:
                try:
                    save_diff(task, directory)
                except (ValueError, OSError):
                    pass
                task.elapsed_seconds = previous_elapsed + time.monotonic() - started
                self.store.finish_execution(task)
                self.store.event(
                    task,
                    "execution_finished",
                    {"state": task.state.value, "elapsed_seconds": task.elapsed_seconds},
                )
                self.store.export_events(task, directory)
                for file in directory.rglob("*"):
                    if file.is_file():
                        self.store.artifact(task, file, "evidence")
            return task

    @staticmethod
    def _validate_workspace(task: Task) -> None:
        expected = task.project / ".engineering" / "worktrees" / task.id
        if task.workspace is None or task.workspace.resolve() != expected.resolve():
            raise ValueError("Invalid or missing saved workspace")
        if not task.workspace.is_dir():
            raise ValueError("Saved workspace is missing; no side effects will be replayed")
        if git(task.workspace, "rev-parse", "HEAD") != task.base_commit:
            raise ValueError("Workspace HEAD changed; automatic continuation is unsafe")

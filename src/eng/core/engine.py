import asyncio
import hashlib
import re
import time
from collections.abc import Callable
from pathlib import Path

from eng.agents import execute_role, parse_handoff, workspace_digest
from eng.context.cache import ContextCache
from eng.context.packet import build_packet
from eng.core.accounting import budget_stop_reason
from eng.core.models import (
    Budgets,
    ClassificationOverrides,
    InvocationTelemetry,
    ProviderRequest,
    ProviderResult,
    RepairAttempt,
    Role,
    State,
    Task,
    TaskType,
    identity,
)
from eng.core.plan import outside_ownership
from eng.core.policy import TERMINAL, completion_gate
from eng.core.reuse import attestation_problem, attested_planner_handoff
from eng.core.routing import route_model
from eng.core.workflow import (
    classify_task,
    escalate_classification,
    failure_signature,
    select_workflow,
    workflow_completion_gate,
)
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
from eng.storage.store import PlanBudgetStop, Store
from eng.verification.runner import run_checks

ROLE_STATES = {
    Role.PLANNER: State.PLANNING,
    Role.ENGINEER: State.IMPLEMENTING,
    Role.DEBUGGER: State.DEBUGGING,
    Role.REVIEWER: State.REVIEWING,
}


class Engine:
    """Sequential adaptive shell; all policy and role effects enter explicitly."""

    def __init__(
        self, store: Store, provider: Provider, *, context_cache_enabled: bool = False
    ) -> None:
        self.store = store
        self.provider = provider
        self.context_cache_enabled = context_cache_enabled

    def _transition(self, task: Task, state: State, message: str = "") -> None:
        if task.state == state:
            task.message = message
            self.store.checkpoint(task)
        else:
            self.store.transition(task, state, message)

    def _classify(self, task: Task, paths: list[str] | None = None) -> None:
        inferred = classify_task(task.spec)
        task.classification = (
            inferred
            if task.classification is None
            else escalate_classification(task.classification, inferred)
        )
        # Initial context must also be fully assessed before the first side effect.
        # Keep overrides here: they are explicit minimum safeguards for this task.
        if len(task.spec.context_paths) > 100:
            context_spec = task.spec.model_copy(deep=True)
            for offset in range(100, len(task.spec.context_paths), 100):
                context_spec.context_paths = task.spec.context_paths[offset : offset + 100]
                task.classification = escalate_classification(
                    task.classification,
                    classify_task(context_spec),
                )
        # The pure classifier bounds each input to 100 paths. Observe every changed
        # path independently, so initial context and path ordering cannot hide risk.
        if paths:
            observed_spec = task.spec.model_copy(deep=True)
            observed_spec.classification_overrides = ClassificationOverrides()
            for offset in range(0, len(paths), 100):
                observed_spec.context_paths = paths[offset : offset + 100]
                task.classification = escalate_classification(
                    task.classification,
                    classify_task(observed_spec),
                )
        selected = select_workflow(task.classification, task.config.workflow)
        if task.workflow is None:
            task.workflow = selected
        else:
            task.workflow.planner |= selected.planner
            task.workflow.reviewer |= selected.reviewer
            task.workflow.approval_required |= selected.approval_required
        self.store.checkpoint(task)

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
                "reviewed",
            }:
                raise ValueError("Task has no implementation to verify")
            task.execution_id = identity()
            self.store.start_execution(task)
            directory = task.project / ".engineering" / "artifacts" / task.id / task.execution_id
            directory.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            previous_elapsed = task.elapsed_seconds
            context_cache = ContextCache() if self.context_cache_enabled else None

            def remaining() -> float:
                return (
                    task.spec.budgets.wall_seconds - previous_elapsed - (time.monotonic() - started)
                )

            def cancelled() -> bool:
                return self.store.cancelled(task.id)

            try:
                if cancelled():
                    self._transition(task, State.CANCELLED, "Cancellation acknowledged")
                    return task
                if remaining() <= 0:
                    self._transition(
                        task, State.PAUSED, "Wall-clock budget exhausted; extend explicitly"
                    )
                    return task
                if resume and task.checkpoint == "provider_started" and not verify_only:
                    self._transition(
                        task,
                        State.PAUSED,
                        "Provider outcome unknown; inspect workspace, then resume --verify-only",
                    )
                    return task
                if resume and task.state != State.PAUSED:
                    self._transition(task, State.PAUSED, "Recovered interrupted execution")
                self._transition(task, State.CLASSIFYING)
                self._classify(task)
                assert task.classification is not None and task.workflow is not None
                if task.classification.task_type == TaskType.QUESTION:
                    self._transition(
                        task,
                        State.BLOCKED,
                        "Read-only question: use a direct assistant conversation; no engineering "
                        "workspace or model call was created. "
                        "Submit a concrete change to run checks.",
                    )
                    return task
                if task.workflow.approval_required and not task.spec.human_approved:
                    self._transition(
                        task,
                        State.PAUSED,
                        "High-risk work requires explicit --approve-high-risk before execution",
                    )
                    return task
                self._transition(task, State.PREPARING_CONTEXT)
                if task.workspace is None:
                    prepare(task)
                    task.checkpoint = "prepared"
                    task.next_role = Role.PLANNER if task.workflow.planner else Role.ENGINEER
                    self.store.checkpoint(task)
                else:
                    self._validate_workspace(task)
                if not self.provider.capabilities.file_editing and not verify_only:
                    raise ValueError("Provider does not support file editing")
                if verify_only:
                    # This is the user's acknowledgement after inspecting uncertain work.
                    # A planner's unknown result must never satisfy required planning.
                    unknown_role = task.pending_role or Role.ENGINEER
                    if task.checkpoint == "provider_started":
                        self.store.event(
                            task,
                            "unknown_outcome_acknowledged",
                            {
                                "role": unknown_role.value,
                                "invocation_id": task.pending_invocation_id,
                            },
                        )
                        task.next_role = (
                            Role.PLANNER
                            if unknown_role == Role.PLANNER
                            else Role.REVIEWER
                            if unknown_role == Role.REVIEWER
                            else None
                        )
                        task.pending_role = None
                        task.pending_invocation_id = None
                        task.pending_model = None
                    task.checkpoint = "implemented"
                    self.store.checkpoint(task)
                elif task.checkpoint in {"implemented", "verified", "reviewed"} and not (
                    task.next_role == Role.DEBUGGER
                    and task.repairs
                    and task.repairs[-1].handoff is None
                ):
                    # Manual inspection/edits and interrupted checks require fresh evidence.
                    task.checkpoint = "implemented"
                    self.store.checkpoint(task)
                elif task.next_role is None:
                    task.next_role = (
                        Role.PLANNER
                        if task.workflow.planner and not task.planning_completed
                        else Role.ENGINEER
                    )
                    self.store.checkpoint(task)

                check_round = 0
                evidence = self._failure_evidence(task)
                pending = task.repairs[-1] if task.repairs else None
                if (
                    task.next_role == Role.DEBUGGER
                    and pending is not None
                    and pending.handoff is None
                    and pending.failure_signature.startswith("review:")
                ):
                    review = next(
                        (h for h in reversed(task.handoffs) if h.role == Role.REVIEWER), None
                    )
                    if review is not None:
                        evidence = self._review_evidence(review.findings)
                while task.state not in TERMINAL:
                    if cancelled():
                        self._transition(task, State.CANCELLED, "Cancellation acknowledged")
                        break
                    if remaining() <= 0:
                        self._transition(task, State.PAUSED, "Wall-clock budget exhausted")
                        break
                    if task.checkpoint == "implemented":
                        self._transition(task, State.VERIFYING)
                        self._validate_workspace(task)
                        assert task.workspace is not None
                        if not self._protect(task):
                            break
                        self._classify(
                            task, changed_paths(task.workspace, task.base_commit or "HEAD")
                        )
                        if task.workflow.approval_required and not task.spec.human_approved:
                            self._transition(
                                task,
                                State.PAUSED,
                                "Changed paths require explicit --approve-high-risk "
                                "before verification or further model calls",
                            )
                            break
                        task.review_passed = False
                        task.review_digest = None
                        task.verified_digest = None
                        self.store.checkpoint(task)  # invalidate evidence BEFORE running checks
                        check_dir = directory / (
                            "checks" if check_round == 0 else f"checks-{check_round + 1}"
                        )
                        check_round += 1
                        task.verification = await run_checks(
                            task.workspace,
                            task.config.checks,
                            check_dir,
                            cancelled,
                            remaining(),
                        )
                        self.store.verification(task)
                        self._validate_workspace(task)
                        if not self._protect(task):
                            break
                        self._classify(
                            task, changed_paths(task.workspace, task.base_commit or "HEAD")
                        )
                        task.verified_digest = workspace_digest(task.workspace)
                        task.checkpoint = "verified"
                        self.store.checkpoint(task)
                        if cancelled():
                            self._transition(task, State.CANCELLED, "Verification cancelled")
                            break
                        if remaining() <= 0:
                            self._transition(
                                task,
                                State.PAUSED,
                                "Wall-clock budget exhausted during verification",
                            )
                            break
                        if task.workflow.approval_required and not task.spec.human_approved:
                            self._transition(
                                task,
                                State.PAUSED,
                                "Changed paths require explicit --approve-high-risk "
                                "before continuation",
                            )
                            break
                        accepted, reason = completion_gate(task.verification)
                        evidence = self._failure_evidence(task)
                        if not accepted:
                            if verify_only:
                                self._transition(task, State.BLOCKED, reason)
                                break
                            signature = self._check_signature(task, evidence)
                            if not self._schedule_repair(task, signature, reason):
                                break
                        elif task.workflow.planner and not task.planning_completed:
                            task.next_role = Role.PLANNER
                        elif task.workflow.reviewer:
                            task.next_role = Role.REVIEWER
                        else:
                            task.next_role = None
                        self.store.checkpoint(task)
                        if verify_only:
                            accepted, reason = workflow_completion_gate(task)
                            self._transition(
                                task,
                                State.COMPLETED if accepted else State.PAUSED,
                                reason
                                if accepted
                                else reason + "; resume explicitly to run the pending role",
                            )
                            break
                    if task.next_role is None:
                        self._validate_workspace(task)
                        assert task.workspace is not None
                        if task.verified_digest != workspace_digest(task.workspace):
                            self._transition(
                                task, State.BLOCKED, "Workspace changed after verification"
                            )
                            break
                        accepted, reason = workflow_completion_gate(task)
                        self._transition(
                            task, State.COMPLETED if accepted else State.BLOCKED, reason
                        )
                        break
                    if task.provider_calls >= task.spec.budgets.model_calls:
                        self._transition(
                            task,
                            State.PAUSED,
                            "Model-call budget exhausted; extend explicitly to run "
                            + task.next_role.value,
                        )
                        break
                    if stop_reason := budget_stop_reason(
                        self.store.invocations(task.id), task.spec.budgets
                    ):
                        self._transition(task, State.PAUSED, stop_reason)
                        break
                    role = task.next_role
                    role_records = [r for r in self.store.invocations(task.id) if r.role == role]
                    allocation = task.spec.budgets.role_limits.get(role)
                    if allocation is not None:
                        if (
                            allocation.model_calls is not None
                            and len(role_records) >= allocation.model_calls
                        ):
                            self._transition(
                                task,
                                State.PAUSED,
                                f"Role {role.value} CLI invocation allocation exhausted; "
                                "extend explicitly",
                            )
                            break
                        role_budgets = Budgets.model_validate(
                            allocation.model_dump(exclude_none=True)
                        )
                        if stop_reason := budget_stop_reason(role_records, role_budgets):
                            self._transition(
                                task, State.PAUSED, f"Role {role.value}: {stop_reason}"
                            )
                            break
                    if stop_reason := self.store.plan_budget_stop_reason(task.id):
                        self._transition(task, State.PAUSED, f"Plan: {stop_reason}")
                        break
                    if role == Role.DEBUGGER and not task.repairs:
                        raise ValueError("Debugger requires a persisted repair attempt")
                    self._validate_workspace(task)
                    if not self._protect(task):
                        break
                    assert task.workspace is not None
                    self._classify(task, changed_paths(task.workspace, task.base_commit or "HEAD"))
                    if task.workflow.approval_required and not task.spec.human_approved:
                        self._transition(
                            task,
                            State.PAUSED,
                            "Changed paths require explicit --approve-high-risk "
                            "before further model calls",
                        )
                        break
                    if (
                        role == Role.PLANNER
                        and task.checkpoint == "prepared"
                        and self._attested_planning(task)
                    ):
                        continue
                    if not await self._invoke(
                        task, role, directory, cancelled, remaining, evidence, context_cache
                    ):
                        break
                    if role == Role.DEBUGGER and self._repair_unchanged(task):
                        break
                    if role == Role.REVIEWER:
                        handoff = task.handoffs[-1]
                        if handoff.verdict == "changes_requested":
                            evidence = self._review_evidence(handoff.findings)
                            signature = "review:" + hashlib.sha256(evidence.encode()).hexdigest()
                            if not self._schedule_repair(
                                task, signature, "Independent review requested changes"
                            ):
                                break
                            self.store.checkpoint(task)
            except (KeyboardInterrupt, asyncio.CancelledError):
                if task.state not in TERMINAL:
                    self._transition(
                        task, State.PAUSED, "Execution interrupted; workspace preserved"
                    )
            except Exception as error:
                if task.state not in TERMINAL:
                    if task.checkpoint == "provider_started":
                        self._transition(
                            task,
                            State.PAUSED,
                            "Provider outcome unknown after error; inspect workspace, "
                            "then resume --verify-only: " + redact(str(error)),
                        )
                    else:
                        self._transition(task, State.FAILED, redact(str(error)))
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
                    {
                        "state": task.state.value,
                        "elapsed_seconds": task.elapsed_seconds,
                    },
                )
                self.store.export_events(task, directory)
                for file in directory.rglob("*"):
                    if file.is_file():
                        self.store.artifact(task, file, "evidence")
            return task

    async def _invoke(
        self,
        task: Task,
        role: Role,
        directory: Path,
        cancelled: Callable[[], bool],
        remaining: Callable[[], float],
        evidence: str,
        context_cache: ContextCache | None = None,
    ) -> bool:
        context_started = time.monotonic()
        prompt = build_packet(task, role, evidence=evidence, cache=context_cache)
        context_duration = time.monotonic() - context_started
        self.store.event(
            task,
            "context",
            {
                "role": role.value,
                "chars": len(prompt),
                "utf8_bytes": len(prompt.encode("utf-8")),
                "duration_seconds": context_duration,
                "cache_enabled": context_cache is not None,
                "cache": context_cache.snapshot() if context_cache is not None else None,
            },
        )
        if cancelled() or remaining() <= 0:
            self._transition(
                task,
                State.CANCELLED if cancelled() else State.PAUSED,
                "Cancellation acknowledged" if cancelled() else "Wall-clock budget exhausted",
            )
            return False
        self._transition(task, ROLE_STATES[role])
        before_reservation = task.model_copy(deep=True)
        invocation_id = identity()
        # The old single-engineer artifact paths remain stable for consumers.
        artifacts = (
            directory
            if role == Role.ENGINEER and task.provider_calls == 0
            else directory / "roles" / f"{role.value[0]}{task.provider_calls + 1}"
        )
        task.pending_role = role
        task.pending_invocation_id = invocation_id
        task.pending_model = self._select_model(task, role)
        task.provider_calls += 1
        task.checkpoint = "provider_started"
        task.review_passed = False
        task.review_digest = None
        if role in {Role.ENGINEER, Role.DEBUGGER}:
            task.verified_digest = None
        try:
            self.store.begin_invocation(task)
        except PlanBudgetStop as error:
            # No side effect was reserved. Restore the pre-call checkpoint/counters
            # before pausing; this must never create a false unknown provider outcome.
            for field in (
                "provider_calls",
                "checkpoint",
                "pending_role",
                "pending_invocation_id",
                "pending_model",
                "review_passed",
                "review_digest",
                "verified_digest",
            ):
                setattr(task, field, getattr(before_reservation, field))
            self._transition(task, State.PAUSED, f"Plan: {error}")
            return False
        assert task.workspace is not None and task.execution_id is not None
        role_started = time.monotonic()
        result: ProviderResult | None = None
        try:
            result = await execute_role(
                self.provider,
                ProviderRequest(
                    task_id=task.id,
                    execution_id=task.execution_id,
                    role=role,
                    workspace=task.workspace,
                    prompt=prompt,
                    model=task.pending_model,
                    timeout_seconds=min(task.spec.budgets.provider_seconds, remaining()),
                ),
                task,
                artifacts,
                cancelled,
            )
        finally:
            role_duration = time.monotonic() - role_started
            if result is not None:
                if result.telemetry is None:
                    result.telemetry = InvocationTelemetry()
                result.telemetry.context_duration_seconds = context_duration
                result.telemetry.role_duration_seconds = role_duration
            self.store.event(
                task,
                "role_elapsed",
                {
                    "invocation_id": invocation_id,
                    "role": role.value,
                    "duration_seconds": role_duration,
                    "provider_duration_seconds": result.duration_seconds if result else None,
                    "timing_scope": "role setup, provider execution and mutation detection",
                },
            )
        task.usage = result.usage
        if cancelled() or result.status == "cancelled":
            self.store.invocation(
                task, result.model_dump_json(), invocation_id=invocation_id, role=role
            )
            self._transition(task, State.CANCELLED, "Provider stopped; workspace preserved")
            return False
        if result.status == "timeout":
            self.store.invocation(
                task, result.model_dump_json(), invocation_id=invocation_id, role=role
            )
            self._transition(
                task, State.PAUSED, "Provider timed out; inspect outcome before verification"
            )
            return False
        if result.status != "success":
            self.store.invocation(
                task, result.model_dump_json(), invocation_id=invocation_id, role=role
            )
            self._transition(task, State.FAILED, f"{result.error_kind}: {result.summary}")
            return False
        try:
            handoff = parse_handoff(role, result.summary, invocation_id)
        except ValueError as error:
            # A known malformed result is not an actionable code failure or unknown edit.
            task.pending_role = None
            task.pending_invocation_id = None
            task.pending_model = None
            task.next_role = role
            task.checkpoint = "verified" if role == Role.REVIEWER else "prepared"
            self.store.complete_invocation(task, result.model_dump_json(), invocation_id, role)
            self._transition(task, State.BLOCKED, "Invalid role handoff: " + str(error))
            return False
        task.handoffs.append(handoff)
        task.pending_role = None
        task.pending_invocation_id = None
        task.pending_model = None
        if role == Role.PLANNER:
            task.planning_completed = True
            task.checkpoint = "planned"
            task.next_role = Role.ENGINEER
        elif role in {Role.ENGINEER, Role.DEBUGGER}:
            task.checkpoint = "implemented"
            task.next_role = None
            if role == Role.DEBUGGER:
                task.repairs[-1].handoff = handoff
        else:
            task.checkpoint = "reviewed"
            task.next_role = None
            task.review_passed = handoff.verdict == "pass"
            task.review_digest = workspace_digest(task.workspace) if task.review_passed else None
        self.store.complete_invocation(task, result.model_dump_json(), invocation_id, role)
        return True

    def _select_model(self, task: Task, role: Role) -> str | None:
        """Explicit task model, else the first matching E3 route, else role_models.

        Routes use the current classification, so escalation selects the matching
        stronger route. A route the provider cannot honour is skipped, never forced.
        """
        if task.spec.model is not None:
            return task.spec.model
        classification = task.classification
        decision = (
            route_model(task.config.routing, classification, role)
            if classification is not None
            else None
        )
        if decision is not None and classification is not None:
            payload = {
                "role": role.value,
                "route": decision.label,
                "index": decision.index,
                "model": decision.model,
                "complexity": classification.complexity.value,
                "risk": classification.risk.value,
            }
            if self.provider.capabilities.model_selection:
                self.store.event(task, "model_routed", payload)
                return decision.model
            self.store.event(
                task,
                "route_skipped",
                {**payload, "reason": f"provider {self.provider.name} has no model selection"},
            )
        return task.config.role_models.get(role)

    def _attested_planning(self, task: Task) -> bool:
        """Satisfy initial planning from a valid human plan attestation, without a call.

        Only before any implementation ("prepared"): planning that changed paths make
        due later is changed-scope reasoning and always uses the model planner.
        """
        attestation = task.spec.plan_attestation
        if attestation is None:
            return False
        problem = attestation_problem(attestation, task.spec, task.config, task.classification)
        if problem is not None:
            self.store.event(
                task,
                "attestation_rejected",
                {"attestation_id": attestation.id, "reason": problem},
            )
            return False
        self._transition(task, State.PLANNING, "Planning satisfied by human plan attestation")
        task.handoffs.append(attested_planner_handoff(attestation))
        task.planning_completed = True
        task.checkpoint = "planned"
        task.next_role = Role.ENGINEER
        self.store.event(
            task,
            "planning_attested",
            {
                "attestation_id": attestation.id,
                "plan": attestation.plan_id,
                "node": attestation.node_id,
                "revision": attestation.revision,
                "source": attestation.source,
            },
        )
        self.store.checkpoint(task)
        return True

    def _schedule_repair(self, task: Task, signature: str, reason: str) -> bool:
        assert task.workflow is not None
        if not signature:
            self._transition(
                task, State.BLOCKED, reason + "; repair requires actionable required failures"
            )
            return False
        if any(attempt.failure_signature == signature for attempt in task.repairs):
            self._transition(
                task, State.BLOCKED, "Repeated identical failure; inspect before another repair"
            )
            return False
        if len(task.repairs) >= task.workflow.max_repairs:
            self._transition(task, State.BLOCKED, "Repair limit reached; " + reason)
            return False
        shortfall = self._repair_shortfall(task)
        if shortfall and not signature.startswith("review:"):
            # Resume re-runs checks first, so failed checks need no durable pending repair.
            self._transition(
                task,
                State.BLOCKED,
                f"{reason}; {shortfall}, extend explicitly or inspect and resume checks",
            )
            return False
        assert task.workspace is not None
        task.repairs.append(
            RepairAttempt(
                number=len(task.repairs) + 1,
                failure_signature=signature,
                base_digest=workspace_digest(task.workspace),
            )
        )
        task.next_role = Role.DEBUGGER
        self.store.checkpoint(task)  # retry consumed BEFORE the debugger side effect
        if shortfall:
            # Review findings are only reproducible by another model call, so keep the
            # repair pending: an explicit extension runs the debugger, not a fresh review.
            self._transition(
                task, State.PAUSED, f"{reason}; {shortfall}, extend explicitly to run debugger"
            )
            return False
        return True

    def _repair_unchanged(self, task: Task) -> bool:
        """Pause when a repair left the workspace byte-identical (E4).

        Re-running deterministic checks or re-reviewing an unchanged tree cannot change
        the outcome deterministically and a re-review costs a model call. The task stays
        at `implemented`: resume re-runs checks after human inspection or edits.
        """
        attempt = task.repairs[-1] if task.repairs else None
        if (
            not task.config.workflow.stop_unchanged_repairs
            or attempt is None
            or attempt.base_digest is None
            or task.workspace is None
        ):
            return False
        if workspace_digest(task.workspace) != attempt.base_digest:
            return False
        self.store.event(task, "repair_unchanged", {"attempt": attempt.number})
        self._transition(
            task,
            State.PAUSED,
            "Repair made no workspace changes; inspect or edit, then resume to re-run checks",
        )
        return True

    def _repair_shortfall(self, task: Task) -> str | None:
        """Why a repair could not reach its required follow-up roles, or None (E4).

        A repair is the debugger plus, when review is required, a fresh review of the
        repaired tree. Starting a debugger call that the configured allowance cannot
        follow with that review only spends money before the same pause.
        """
        assert task.workflow is not None
        available = task.spec.budgets.model_calls - task.provider_calls
        if not task.config.workflow.repair_headroom:
            return "model-call budget exhausted" if available <= 0 else None
        needed = 2 if task.workflow.reviewer else 1
        if available < needed:
            if available <= 0:
                return "model-call budget exhausted"
            return (
                f"repair needs {needed} model calls (debugger and required review); "
                f"{available} remain"
            )
        records = self.store.invocations(task.id)
        roles = (Role.DEBUGGER, Role.REVIEWER) if task.workflow.reviewer else (Role.DEBUGGER,)
        for role in roles:
            allocation = task.spec.budgets.role_limits.get(role)
            if allocation is not None and allocation.model_calls is not None:
                used = sum(1 for record in records if record.role == role)
                if used >= allocation.model_calls:
                    return f"role {role.value} CLI invocation allocation exhausted"
        return None

    @staticmethod
    def _review_evidence(findings: list[str]) -> str:
        return "Independent review findings:\n" + "\n".join(findings)

    @staticmethod
    def _failure_evidence(task: Task) -> str:
        excerpts = []
        for result in task.verification:
            if not result.required or result.outcome != "FAIL":
                continue
            log = ""
            if result.artifact:
                path = Path(result.artifact)
                root = task.project / ".engineering" / "artifacts" / task.id
                if path.resolve().is_relative_to(root.resolve()) and path.is_file():
                    # A UTF-8 character occupies at most four bytes. Read enough
                    # for the existing character tail without loading the full log.
                    with path.open("rb") as handle:
                        size = handle.seek(0, 2)
                        handle.seek(max(0, size - 20000))
                        tail = handle.read(20000).decode("utf-8", errors="replace")
                    log = tail.replace("\r\n", "\n").replace("\r", "\n")[-5000:]
            if task.workspace:
                log = log.replace(str(task.workspace), "<workspace>")
                log = log.replace(str(task.workspace).replace("\\", "/"), "<workspace>")
            log = re.sub(r'(?:[A-Za-z]:[\\/]|/)[^\s"\']+', "<path>", log)
            log = re.sub(r"\b\d+(?:\.\d+)?\s*(?:ms|seconds?|secs?)\b", "<duration>", log)
            log = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", log)
            log = re.sub(r"\b\d+(?:\.\d+)?s\b", "<duration>", log)
            excerpts.append(f"{result.check_id}: {result.outcome}\n{redact(log)}")
        return "\n".join(excerpts)[:12000]

    @staticmethod
    def _check_signature(task: Task, evidence: str) -> str:
        signature = failure_signature(task.verification)
        if not signature:
            return ""
        return hashlib.sha256((signature + "\n" + evidence).encode()).hexdigest()

    def _protect(self, task: Task) -> bool:
        assert task.workspace is not None
        changed = changed_paths(task.workspace, task.base_commit or "HEAD")
        forbidden = protected_changes(changed, task.config.protected_paths)
        if forbidden:
            self._transition(task, State.FAILED, "Protected files changed: " + ", ".join(forbidden))
            return False
        if task.spec.owned_paths:
            outside = outside_ownership(changed, task.spec.owned_paths)
            if outside:
                self._transition(
                    task, State.FAILED, "Changed paths outside ownership: " + ", ".join(outside)
                )
                return False
        return True

    @staticmethod
    def _validate_workspace(task: Task) -> None:
        expected = task.project / ".engineering" / "worktrees" / task.id
        if task.workspace is None or task.workspace.resolve() != expected.resolve():
            raise ValueError("Invalid or missing saved workspace")
        if not task.workspace.is_dir():
            raise ValueError("Saved workspace is missing; no side effects will be replayed")
        if git(task.workspace, "rev-parse", "HEAD") != task.base_commit:
            raise ValueError("Workspace HEAD changed; automatic continuation is unsafe")

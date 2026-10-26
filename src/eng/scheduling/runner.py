"""Plan coordinator: dependency scheduling, bounded concurrency, serialized integration.

One coordinator per plan (OS lock) launches ready nodes as ordinary tasks in worker
threads. Each worker owns its Store connection, event loop and Git worktree, so the M3-M5
engine runs unchanged and concurrently. At most ``MAX_CONCURRENCY`` nodes run per project
at any time, across plans and processes (slot locks). Only this coordinator thread writes
the plan record and the integration branch.
"""

import asyncio
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import IO

from eng.core.accounting import budget_stop_reason
from eng.core.engine import Engine
from eng.core.models import (
    Budgets,
    ClassificationOverrides,
    DependencyHandoff,
    InvocationRecord,
    PlanAttestation,
    ProjectConfig,
    Risk,
    State,
    Task,
    TaskSpec,
    identity,
)
from eng.core.plan import (
    MAX_CONCURRENCY,
    NodeStatus,
    PlanLimits,
    PlanNode,
    PlanRecord,
    PlanSpec,
    PlanStatus,
    derive_plan_status,
    node_description,
    node_status_for_task,
    path_owned,
    ready_nodes,
    resolve_budgets,
    skipped_nodes,
)
from eng.core.policy import TERMINAL
from eng.core.reuse import (
    handoff_problem,
    node_scope_digest,
    policy_digest,
)
from eng.execution.integrate import changed_between, create_integration, head, is_ancestor
from eng.execution.process import redact
from eng.execution.workspace import task_lock, try_lock, unlock
from eng.projects.config import load_config
from eng.providers.base import Provider
from eng.scheduling.integration import integrate_node, reconcile
from eng.storage.store import Store

ProviderFactory = Callable[[str, ProjectConfig], Provider]


class SlotPool:
    """Project-wide concurrency cap shared by every plan coordinator process."""

    def __init__(self, root: Path, size: int = MAX_CONCURRENCY) -> None:
        self.root = root
        self.size = min(size, MAX_CONCURRENCY)

    def acquire(self) -> IO[bytes] | None:
        for index in range(self.size):
            handle = try_lock(self.root / ".engineering" / "locks" / f"slot-{index}.lock")
            if handle is not None:
                return handle
        return None

    @staticmethod
    def release(handle: IO[bytes]) -> None:
        unlock(handle)


class PlanRunner:
    def __init__(
        self, root: Path, provider_factory: ProviderFactory, *, poll_seconds: float = 0.1
    ) -> None:
        self.root = root
        self.provider_factory = provider_factory
        self.poll_seconds = poll_seconds

    def create(
        self, store: Store, spec: PlanSpec, config: ProjectConfig | None = None
    ) -> PlanRecord:
        """Validate providers, create the eng-owned branch/worktree and persist the plan."""
        config = config or load_config(self.root)
        if not any(check.required and check.confirmed for check in config.checks):
            # Without one, no node could ever pass the completion gate: fail before any cost.
            raise ValueError(
                "A plan needs at least one confirmed required check in .engineering/project.yaml"
            )
        for name in {node.provider or spec.provider or config.provider for node in spec.nodes}:
            self.provider_factory(name, config)  # unknown providers fail before any effect
        plan_id = identity()
        branch, base, workspace = create_integration(self.root, plan_id)
        plan = PlanRecord(
            id=plan_id,
            project=self.root,
            spec=spec,
            budget_schema_version=2,
            nodes=[
                PlanNode(
                    spec=node,
                    effective_budgets=resolve_budgets(
                        config.budgets, spec.node_budgets, node.budgets
                    ),
                    effective_max_repairs=(
                        node.max_repairs
                        if node.max_repairs is not None
                        else spec.node_max_repairs
                        if spec.node_max_repairs is not None
                        else config.workflow.max_repairs
                    ),
                )
                for node in spec.nodes
            ],
            base_commit=base,
            branch=branch,
            workspace=workspace,
            head_commit=base,
        )
        store.create_plan(plan)
        return plan

    # -- execution ---------------------------------------------------------------------

    def _execute(self, task_id: str, resume: bool) -> str:
        store = Store(self.root)
        try:
            task = store.load(task_id)
            provider = self.provider_factory(task.spec.provider, task.config)
            result = asyncio.run(Engine(store, provider).execute(task_id, resume=resume))
            return result.state.value
        finally:
            store.close()

    def _reuse(
        self, store: Store, plan: PlanRecord, node: PlanNode, config: ProjectConfig
    ) -> tuple[list[DependencyHandoff], PlanAttestation | None]:
        """Validate E2 reuse inputs against the launch revision; drop what no longer holds.

        Dropped items fall back to the uncached path (no dependency summary, model
        planner). The manifest event records exactly what this launch reused and why
        anything was not.
        """
        if not plan.spec.context_reuse and node.attestation is None:
            return [], None
        launch = plan.head_commit
        handoffs: list[DependencyHandoff] = []
        manifest: list[dict[str, object]] = []
        if plan.spec.context_reuse:
            for dependency_id in node.spec.depends_on:
                handoff = plan.node(dependency_id).handoff
                later: set[str] = set()
                if handoff is None:
                    problem: str | None = "no recorded handoff"
                else:
                    problem = handoff_problem(handoff, config)
                    try:
                        if problem is None and not is_ancestor(
                            self.root, handoff.integrated_commit, launch
                        ):
                            problem = "integrated commit is not in the launch revision"
                        if problem is None:
                            later = set(
                                changed_between(self.root, handoff.integrated_commit, launch)
                            )
                    except ValueError as error:  # unknown commit: invalid, never fatal
                        problem = "revision check failed: " + redact(str(error))[:200]
                if handoff is None or problem is not None:
                    manifest.append({"node": dependency_id, "omitted": problem})
                    continue
                reused = handoff.model_copy(
                    update={"stale_files": [f for f in handoff.changed_files if f in later]}
                )
                handoffs.append(reused)
                manifest.append(
                    {
                        "node": dependency_id,
                        "integrated_commit": reused.integrated_commit,
                        "digest": reused.digest,
                        "stale_files": reused.stale_files,
                    }
                )
        attestation = node.attestation
        attestation_reason: str | None = None
        if attestation is not None:
            if (attestation.plan_id, attestation.node_id) != (plan.id, node.spec.id):
                attestation_reason = "attestation belongs to another plan node"
            elif attestation.scope_digest != node_scope_digest(node.spec):
                attestation_reason = "node scope differs from the attested scope"
            elif attestation.policy_digest != policy_digest(config):
                attestation_reason = "project verification policy changed since attestation"
            else:
                attestation_reason = self._revision_problem(attestation, node, launch)
            if attestation_reason is not None:
                store.plan_event(
                    plan.id,
                    "attestation_invalidated",
                    {
                        "node": node.spec.id,
                        "attestation_id": attestation.id,
                        "reason": attestation_reason,
                    },
                )
                attestation = None
        store.plan_event(
            plan.id,
            "context_manifest",
            {
                "node": node.spec.id,
                "revision": launch,
                "dependencies": manifest,
                "attestation_id": attestation.id if attestation is not None else None,
            },
        )
        return handoffs, attestation

    def _revision_problem(
        self, attestation: PlanAttestation, node: PlanNode, launch: str
    ) -> str | None:
        try:
            if not is_ancestor(self.root, attestation.revision, launch):
                return "attested revision is not in the launch revision"
            edited = [
                path
                for path in changed_between(self.root, attestation.revision, launch)
                if path_owned(path, node.spec.owns)
            ]
        except ValueError as error:  # unknown commit: invalid, never fatal
            return "revision check failed: " + redact(str(error))[:200]
        if edited:
            return "owned paths changed since attestation: " + ", ".join(edited[:10])
        return None

    def _new_task(
        self,
        plan: PlanRecord,
        node: PlanNode,
        config: ProjectConfig,
        approve: bool,
        *,
        dependency_handoffs: list[DependencyHandoff] | None = None,
        attestation: PlanAttestation | None = None,
    ) -> Task:
        spec = plan.spec
        if node.effective_budgets is None:
            if plan.budget_schema_version == 1 and spec.node_budgets is not None:
                # Old saved plans serialized a full Budgets object. Its null
                # reported thresholds deliberately replaced project thresholds.
                node.effective_budgets = Budgets.model_validate(
                    spec.node_budgets.model_dump(exclude_none=True)
                )
            else:
                node.effective_budgets = resolve_budgets(
                    config.budgets, spec.node_budgets, node.spec.budgets
                )
        if node.effective_max_repairs is None:
            node.effective_max_repairs = (
                node.spec.max_repairs
                if node.spec.max_repairs is not None
                else spec.node_max_repairs
                if spec.node_max_repairs is not None
                else config.workflow.max_repairs
            )
        budgets = node.effective_budgets.model_copy(deep=True)
        config = config.model_copy(deep=True)
        config.workflow.max_repairs = node.effective_max_repairs
        task_spec = TaskSpec(
            description=node_description(node.spec),
            acceptance=node.spec.acceptance,
            provider=node.spec.provider or spec.provider or config.provider,
            model=node.spec.model,
            budgets=budgets,
            context_paths=node.spec.context_paths,
            classification_overrides=ClassificationOverrides(risk=node.spec.risk),
            human_approved=approve,
            owned_paths=node.spec.owns,
            base_commit=plan.head_commit,
            interfaces=node.spec.interfaces,
            dependency_handoffs=dependency_handoffs or [],
            plan_attestation=attestation,
        )
        return Task(project=self.root, spec=task_spec, config=config)

    def run(
        self,
        plan_id: str,
        *,
        keep_going: bool = False,
        approve_high_risk: bool = False,
        resume: bool = False,
        clear_limits: bool = False,
    ) -> PlanRecord:
        """Schedule until nothing more can progress; returns the persisted plan."""
        store = Store(self.root)
        try:
            with task_lock(self.root, f"plan-{plan_id}"):
                return self._run(
                    store, plan_id, keep_going, approve_high_risk, resume, clear_limits
                )
        finally:
            store.close()

    def _run(
        self,
        store: Store,
        plan_id: str,
        keep_going: bool,
        approve: bool,
        resume: bool,
        clear_limits: bool,
    ) -> PlanRecord:
        plan = store.load_plan(plan_id)
        if plan.status == PlanStatus.PROMOTED:
            raise ValueError("Plan is already promoted")
        if plan.cancel_requested or plan.status == PlanStatus.CANCELLED:
            raise ValueError("Plan was cancelled; create a new plan")
        reconcile(store, plan)
        plan.message = ""
        if clear_limits:
            # Explicit human action, like `resume --clear-reported-limits` for one task.
            plan.spec.limits = PlanLimits()
            plan.message = ""
            store.plan_event(plan.id, "limits_cleared", {"source": "explicit_cli"})
            store.save_plan(plan)
            store.clear_plan_reservations(plan.id)
        config = load_config(self.root)
        pool = SlotPool(self.root, plan.spec.concurrency)
        futures: dict[Future[str], tuple[str, IO[bytes]]] = {}
        queue: list[str] = []
        for node in plan.nodes:
            # A coordinator may die after node_finished/VERIFIED was persisted but
            # before settling its launch lease (or after integration). Reconcile
            # every membership, not only RUNNING nodes; settlement takes the task's
            # nonblocking OS lock and leaves an active direct continuation alone.
            if node.task_id:
                store.settle_plan_launch(plan.id, node.spec.id)
            interrupted = node.status == NodeStatus.RUNNING  # a previous coordinator died
            if interrupted or (resume and node.status in {NodeStatus.PAUSED, NodeStatus.BLOCKED}):
                task = store.load(node.task_id) if node.task_id else None
                if task is not None and task.state == State.COMPLETED:
                    node.status = NodeStatus.VERIFIED
                    store.settle_plan_launch(plan.id, node.spec.id)
                elif task is not None and task.state in TERMINAL:
                    node.status = node_status_for_task(task.state)
                    store.settle_plan_launch(plan.id, node.spec.id)
                else:
                    queue.append(node.spec.id)
        store.plan_event(
            plan.id,
            "run_started",
            {"keep_going": keep_going, "resume": resume, "approve_high_risk": approve},
        )
        if approve:
            store.plan_event(plan.id, "human_approved", {"source": "explicit_cli", "scope": "all"})
        limit_reason: str | None = None
        cancelling = False
        waiting = False
        executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENCY, thread_name_prefix="eng-node")

        def collect(done: set[Future[str]]) -> None:
            for future in done:
                node_id, slot = futures.pop(future)
                node = plan.node(node_id)
                try:
                    try:
                        future.result()
                        task = store.load(node.task_id or "")
                        node.status = node_status_for_task(task.state)
                        node.message = task.message
                    except Exception as error:  # noqa: BLE001 - surfaced as a blocked node
                        node.status = NodeStatus.BLOCKED
                        node.message = redact(f"Node runner error: {error}")
                    store.plan_event(
                        plan.id, "node_finished", {"node": node_id, "status": node.status.value}
                    )
                    store.save_plan(plan)
                    store.settle_plan_launch(plan.id, node_id)
                finally:
                    # Release only after the finish is recorded: the event log must never
                    # show more nodes in flight than slots that were really held.
                    pool.release(slot)

        def launch(node: PlanNode) -> bool:
            nonlocal limit_reason
            slot = pool.acquire()
            if slot is None:
                return False
            try:
                resumed = False
                if node.task_id is None:
                    handoffs, attestation = self._reuse(store, plan, node, config)
                    task = self._new_task(
                        plan,
                        node,
                        config,
                        approve,
                        dependency_handoffs=handoffs,
                        attestation=attestation,
                    )
                    node.base_commit = plan.head_commit
                else:
                    task = store.load(node.task_id)
                    resumed = task.state != State.CREATED
                if reason := store.claim_plan_launch(plan, node, task):
                    pool.release(slot)
                    if not futures:
                        limit_reason = reason
                        plan.message = reason
                        store.plan_event(plan.id, "limit_reached", {"message": reason})
                    return False
                futures[executor.submit(self._execute, task.id, resumed)] = (
                    node.spec.id,
                    slot,
                )
            except BaseException:
                pool.release(slot)
                raise
            return True

        try:
            while True:
                if not cancelling and store.plan_cancelled(plan.id):
                    cancelling = True
                    for node in plan.nodes:
                        if node.task_id:
                            store.cancel(node.task_id)
                if futures:
                    done, _ = wait(futures, timeout=self.poll_seconds, return_when=FIRST_COMPLETED)
                    collect(done)
                if not cancelling:
                    for node in plan.nodes:
                        if node.status == NodeStatus.VERIFIED:
                            integrate_node(store, plan, node, lambda: store.plan_cancelled(plan.id))
                    for node_id in skipped_nodes(plan.spec, plan.statuses()):
                        skipped = plan.node(node_id)
                        skipped.status = NodeStatus.SKIPPED
                        skipped.message = "An upstream node failed or was cancelled"
                        store.plan_event(plan.id, "node_skipped", {"node": node_id})
                    store.save_plan(plan)
                launched = False
                starved = False  # work is ready but another plan holds every project slot
                if not cancelling and limit_reason is None and not futures:
                    records: list[InvocationRecord] = [
                        record
                        for node in plan.nodes
                        if node.task_id
                        for record in store.invocations(node.task_id)
                    ]
                    limit_reason = budget_stop_reason(records, plan.spec.limits.as_budgets())
                    if limit_reason:
                        plan.message = limit_reason
                        store.plan_event(plan.id, "limit_reached", {"message": limit_reason})
                if not cancelling and limit_reason is None:
                    free = plan.spec.concurrency - len(futures)
                    if futures and any(
                        value is not None for value in plan.spec.limits.model_dump().values()
                    ):
                        # Admission is serialized without calibrated estimates. Do not
                        # repeatedly contend for a lease while its owner is still running.
                        free = 0
                    while queue and free > 0:
                        node = plan.node(queue[0])
                        task = store.load(node.task_id) if node.task_id else None
                        if task is not None and task.state == State.COMPLETED:
                            node.status = NodeStatus.VERIFIED  # retry integration only
                            queue.pop(0)
                            launched = True
                            continue
                        if task is not None and task.state in TERMINAL:
                            node.status = node_status_for_task(task.state)
                            queue.pop(0)
                            continue
                        if not launch(node):
                            starved = True
                            break
                        queue.pop(0)
                        free -= 1
                        launched = True
                    ready = ready_nodes(
                        plan.spec,
                        plan.statuses(),
                        slots_free=free if not queue else 0,
                        keep_going=keep_going,
                    )
                    for node_id in ready:
                        if not launch(plan.node(node_id)):
                            starved = True
                            break
                        launched = True
                if not futures and not launched:
                    if starved and not cancelling and limit_reason is None:
                        # Ready work must never be abandoned because the project's shared
                        # slots are busy elsewhere: wait, then retry (cancellation breaks).
                        if not waiting:
                            store.plan_event(plan.id, "waiting_for_slot", {})
                            waiting = True
                        time.sleep(self.poll_seconds * 5)
                        continue
                    if not any(n.status == NodeStatus.VERIFIED for n in plan.nodes):
                        break
        except KeyboardInterrupt:
            for node in plan.nodes:
                if node.status == NodeStatus.RUNNING and node.task_id:
                    store.cancel(node.task_id)
            cancelling = True
            plan.message = "Interrupted; running nodes were cancelled and workspaces retained"
        finally:
            executor.shutdown(wait=True)
            collect(set(futures))
        if cancelling:
            for node in plan.nodes:
                if node.status not in {NodeStatus.INTEGRATED, NodeStatus.SKIPPED}:
                    node.status = NodeStatus.CANCELLED
                    node.message = node.message or "Plan cancelled"
        plan.status = derive_plan_status(list(plan.statuses().values()))
        if limit_reason and plan.status not in {
            PlanStatus.READY,
            PlanStatus.FAILED,
            PlanStatus.CANCELLED,
            PlanStatus.BLOCKED,
        }:
            plan.status = PlanStatus.PAUSED
        plan.message = plan.message or _summary(plan)
        store.plan_event(plan.id, "run_finished", {"status": plan.status.value})
        store.save_plan(plan)
        if plan.status == PlanStatus.READY and head(plan.workspace) != plan.head_commit:
            raise ValueError("Integration worktree diverged from the recorded head")
        return plan

    # -- explicit human actions ----------------------------------------------------------

    def approve_node(self, store: Store, plan_id: str, node_id: str) -> PlanRecord:
        """Record explicit high-risk approval for one node's task; resume to continue."""
        with task_lock(self.root, f"plan-{plan_id}"):
            plan = store.load_plan(plan_id)
            node = plan.node(node_id)
            if node.task_id is None:
                raise ValueError("Node has no task yet; use `plan run --approve-high-risk`")
            with task_lock(self.root, node.task_id):
                task = store.load(node.task_id)
                if task.state in TERMINAL:
                    raise ValueError("Cannot approve a terminal node task")
                task.spec.human_approved = True
                store.checkpoint(task)
                store.event(task, "human_approved", {"source": "explicit_cli", "plan": plan_id})
            store.plan_event(plan_id, "human_approved", {"source": "explicit_cli", "node": node_id})
            return plan

    def attest(
        self, store: Store, plan_id: str, node_ids: list[str], *, revoke: bool = False
    ) -> PlanRecord:
        """Record or revoke explicit human plan attestations (E2); never model-callable.

        An attestation lets a node's own spec satisfy its initial planner step. It binds
        the node scope, verification policy and current integration revision. Review,
        checks, task approval and ownership are unaffected; high-risk nodes are refused.
        """
        if not node_ids:
            raise ValueError("Name at least one node, or use --all")
        with task_lock(self.root, f"plan-{plan_id}"):
            plan = store.load_plan(plan_id)
            if plan.status in {PlanStatus.PROMOTED, PlanStatus.CANCELLED} or plan.cancel_requested:
                raise ValueError(f"Plan is {plan.status.value}; attestations cannot change")
            nodes = [plan.node(node_id) for node_id in dict.fromkeys(node_ids)]
            config = load_config(self.root)
            # Validate every node before changing anything: all or nothing.
            for node in nodes:
                if revoke:
                    self._revocable(store, node)
                elif node.task_id is not None:
                    raise ValueError(
                        f"Node {node.spec.id} has already launched; attest before launch"
                    )
                elif node.spec.risk == Risk.HIGH:
                    raise ValueError(f"Node {node.spec.id} is high-risk and keeps model planning")
            for node in nodes:
                if revoke:
                    self._revoke(store, plan, node)
                    continue
                node.attestation = PlanAttestation(
                    plan_id=plan.id,
                    node_id=node.spec.id,
                    scope_digest=node_scope_digest(node.spec),
                    policy_digest=policy_digest(config),
                    revision=plan.head_commit,
                )
                store.plan_event(
                    plan.id,
                    "plan_attested",
                    {
                        "node": node.spec.id,
                        "attestation_id": node.attestation.id,
                        "revision": plan.head_commit,
                        "source": "explicit_cli",
                    },
                )
            store.save_plan(plan)
            return plan

    @staticmethod
    def _revocable(store: Store, node: PlanNode) -> Task | None:
        """The launched task still holding an unconsumed attestation, if any."""
        if node.attestation is None or node.task_id is None:
            return None
        task = store.load(node.task_id)
        if task.spec.plan_attestation is None:
            return None  # invalidated at launch; only the plan record remains
        if task.state in TERMINAL or task.planning_completed:
            raise ValueError(f"Node {node.spec.id} already completed planning; cannot revoke")
        return task

    def _revoke(self, store: Store, plan: PlanRecord, node: PlanNode) -> None:
        if node.attestation is None:
            return
        attestation_id = node.attestation.id
        if node.task_id is not None:
            with task_lock(self.root, node.task_id):
                task = self._revocable(store, node)  # recheck under the task lock
                if task is not None:
                    task.spec.plan_attestation = None
                    store.checkpoint(task)
                    store.event(task, "attestation_revoked", {"source": "explicit_cli"})
        node.attestation = None
        store.plan_event(
            plan.id,
            "attestation_revoked",
            {"node": node.spec.id, "attestation_id": attestation_id, "source": "explicit_cli"},
        )

    def cancel(self, store: Store, plan_id: str) -> PlanRecord:
        """Persist cancellation; an idle plan is finalized immediately."""
        requested = store.cancel_plan(plan_id)
        plan = store.load_plan(plan_id)
        if not requested:
            return plan
        try:
            with task_lock(self.root, f"plan-{plan_id}"):
                plan = store.load_plan(plan_id)
                for node in plan.nodes:
                    if node.task_id:
                        store.cancel(node.task_id)
                        task = store.load(node.task_id)
                        if task.state not in TERMINAL:
                            with task_lock(self.root, task.id):
                                store.transition(
                                    task, State.CANCELLED, "Plan cancelled; workspace retained"
                                )
                    if node.status not in {NodeStatus.INTEGRATED, NodeStatus.SKIPPED}:
                        node.status = NodeStatus.CANCELLED
                        node.message = "Plan cancelled"
                plan.status = PlanStatus.CANCELLED
                plan.message = "Cancelled while idle; workspaces retained"
                store.save_plan(plan)
        except ValueError:
            pass  # The active coordinator acknowledges the durable request.
        return store.load_plan(plan_id)


def _summary(plan: PlanRecord) -> str:
    counts: dict[str, int] = {}
    for node in plan.nodes:
        counts[node.status.value] = counts.get(node.status.value, 0) + 1
    return ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))

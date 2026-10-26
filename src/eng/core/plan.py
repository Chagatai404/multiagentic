"""Pure plan contracts and scheduling policy: no filesystem, git, threads or storage.

A plan is a dependency graph of owned work items. Two nodes that are not ordered by a
dependency may run concurrently, so their ownership must be provably disjoint; overlap
analysis is conservative and rejects a plan whenever disjointness cannot be shown.
"""

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from fnmatch import fnmatchcase
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from eng.core.models import (
    Budgets,
    Contract,
    DependencyHandoff,
    PlanAttestation,
    Risk,
    Role,
    RoleLimits,
    State,
    VerificationResult,
    identity,
    now,
)

MAX_CONCURRENCY = 3
MAX_NODES = 50
MAX_PATTERNS = 50
NODE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_WILDCARDS = re.compile(r"[*?\[]")
_FORBIDDEN_ROOTS = {".git", ".engineering"}


class NodeStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    VERIFIED = "VERIFIED"  # task COMPLETED, awaiting integration
    INTEGRATED = "INTEGRATED"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class PlanStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    READY = "READY"  # every node integrated and verified; promotion needs approval
    PROMOTED = "PROMOTED"


PROBLEMS = frozenset(
    {NodeStatus.PAUSED, NodeStatus.BLOCKED, NodeStatus.FAILED, NodeStatus.CANCELLED}
)
DEAD = frozenset({NodeStatus.FAILED, NodeStatus.CANCELLED, NodeStatus.SKIPPED})


class BudgetOverrides(Contract):
    """Additive budget fields. Omitted/None fields inherit; clearing is a human action.

    Role thresholds merge field by field and always remain subordinate to task totals.
    Model calls count provider CLI invocations, not the provider's internal turns.
    """

    wall_seconds: float | None = Field(default=None, gt=0, le=86400, allow_inf_nan=False)
    provider_seconds: float | None = Field(default=None, gt=0, le=86400, allow_inf_nan=False)
    model_calls: int | None = Field(default=None, ge=1, le=100)
    context_chars: int | None = Field(default=None, ge=256, le=1000000)
    reported_input_tokens: int | None = Field(default=None, gt=0)
    reported_output_tokens: int | None = Field(default=None, gt=0)
    reported_cost_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    role_limits: dict[Role, RoleLimits] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def legacy_budget(cls, value: object) -> object:
        return value.model_dump() if isinstance(value, Budgets) else value

    @field_validator("role_limits")
    @classmethod
    def model_roles_only(cls, value: dict[Role, RoleLimits]) -> dict[Role, RoleLimits]:
        return Budgets.model_roles_only(value)


def resolve_budgets(base: Budgets, *overrides: BudgetOverrides | None) -> Budgets:
    """Resolve project defaults, plan defaults, then node fields without mutation."""
    values = base.model_dump()
    for override in overrides:
        if override is None:
            continue
        fields = override.model_dump(exclude_none=True)
        roles = fields.pop("role_limits", {})
        values.update(fields)
        for role, limits in roles.items():
            values["role_limits"].setdefault(role, {}).update(limits)
    return Budgets.model_validate(values)


class PlanLimits(Contract):
    """Plan-wide reported-usage stop thresholds, checked before launching a node."""

    reported_input_tokens: int | None = Field(default=None, gt=0)
    reported_output_tokens: int | None = Field(default=None, gt=0)
    reported_cost_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    def as_budgets(self) -> Budgets:
        return Budgets(
            reported_input_tokens=self.reported_input_tokens,
            reported_output_tokens=self.reported_output_tokens,
            reported_cost_usd=self.reported_cost_usd,
        )


def normalize_pattern(pattern: str) -> str:
    """Return a canonical repository-relative pattern or raise ValueError."""
    if "\x00" in pattern or not pattern.strip():
        raise ValueError("Ownership pattern cannot be blank or contain NUL")
    text = pattern.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if text.endswith("/"):
        text += "**"
    candidate = Path(text)
    if text.startswith("/") or candidate.is_absolute() or re.match(r"^[A-Za-z]:", text):
        raise ValueError(f"Ownership pattern must be relative: {pattern}")
    segments = text.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError(f"Unsafe ownership pattern: {pattern}")
    if segments[0].lower() in _FORBIDDEN_ROOTS or any(
        segment.lower() == ".git" for segment in segments
    ):
        raise ValueError(f"Ownership cannot include repository or eng state: {pattern}")
    return "/".join(segments)


def _segments_match(pattern: tuple[str, ...], path: tuple[str, ...]) -> bool:
    @cache
    def walk(i: int, j: int) -> bool:
        if i == len(pattern):
            return j == len(path)
        if pattern[i] == "**":
            return walk(i + 1, j) or (j < len(path) and walk(i, j + 1))
        return j < len(path) and fnmatchcase(path[j], pattern[i]) and walk(i + 1, j + 1)

    return walk(0, 0)


def path_owned(path: str, patterns: Sequence[str]) -> bool:
    """Case-insensitive ownership test; ``**`` spans zero or more directories."""
    parts = tuple(part for part in path.replace("\\", "/").lower().split("/") if part)
    if not parts:
        return False
    return any(
        _segments_match(tuple(normalize_pattern(pattern).lower().split("/")), parts)
        for pattern in patterns
    )


def outside_ownership(paths: Sequence[str], patterns: Sequence[str]) -> list[str]:
    return [path for path in paths if not path_owned(path, patterns)]


def _compatible(left: str, right: str) -> bool:
    left_wild, right_wild = bool(_WILDCARDS.search(left)), bool(_WILDCARDS.search(right))
    if not left_wild and not right_wild:
        return left == right
    if not left_wild:
        return fnmatchcase(left, right)
    if not right_wild:
        return fnmatchcase(right, left)
    return True  # two wildcard segments: assume they can match the same name


def patterns_may_overlap(first: str, second: str) -> bool:
    """True unless no path can match both patterns (conservative for wildcards)."""
    a = tuple(normalize_pattern(first).lower().split("/"))
    b = tuple(normalize_pattern(second).lower().split("/"))

    @cache
    def walk(i: int, j: int) -> bool:
        if i == len(a) and j == len(b):
            return True
        if i == len(a):
            return all(segment == "**" for segment in b[j:])
        if j == len(b):
            return all(segment == "**" for segment in a[i:])
        if a[i] == "**":
            return walk(i + 1, j) or walk(i, j + 1)
        if b[j] == "**":
            return walk(i, j + 1) or walk(i + 1, j)
        return _compatible(a[i], b[j]) and walk(i + 1, j + 1)

    return walk(0, 0)


class PlanNodeSpec(Contract):
    id: str
    description: str = Field(min_length=1, max_length=64000)
    acceptance: list[str] = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    owns: list[str] = Field(min_length=1, max_length=MAX_PATTERNS)
    provider: str | None = None
    model: str | None = None
    context_paths: list[str] = Field(default_factory=list)
    risk: Risk | None = None
    budgets: BudgetOverrides | None = None
    max_repairs: int | None = Field(default=None, ge=0, le=10)
    # Interface contracts this node provides to its dependents (E2); part of its scope.
    interfaces: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not NODE_ID.fullmatch(value):
            raise ValueError("node id must match [a-z0-9][a-z0-9_-]{0,31}")
        return value

    @field_validator("description")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description cannot be blank")
        return value

    @field_validator("acceptance")
    @classmethod
    def acceptance_not_blank(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("acceptance criteria cannot be blank")
        return value

    @field_validator("interfaces")
    @classmethod
    def bounded_interfaces(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 500 for item in value):
            raise ValueError("interface contracts must be nonblank and at most 500 characters")
        return value

    @field_validator("owns")
    @classmethod
    def normalized_owns(cls, value: list[str]) -> list[str]:
        return sorted({normalize_pattern(item) for item in value})


class PlanSpec(Contract):
    name: str = Field(min_length=1, max_length=120)
    nodes: list[PlanNodeSpec] = Field(min_length=1, max_length=MAX_NODES)
    concurrency: int = Field(default=1, ge=1, le=MAX_CONCURRENCY)
    provider: str | None = None
    node_budgets: BudgetOverrides | None = None
    node_max_repairs: int | None = Field(default=None, ge=0, le=10)
    limits: PlanLimits = Field(default_factory=PlanLimits)
    # E2: pass compact typed handoffs of integrated direct dependencies to each node.
    # Off by default; off is the deterministic uncached path.
    context_reuse: bool = False

    @model_validator(mode="after")
    def valid_graph(self) -> "PlanSpec":
        validate_graph(self)
        return self


def ancestors(spec: PlanSpec) -> dict[str, frozenset[str]]:
    """Transitive dependencies per node; raises ValueError on unknown ids or cycles."""
    by_id = {node.id: node for node in spec.nodes}
    result: dict[str, frozenset[str]] = {}
    visiting: set[str] = set()

    def visit(node_id: str) -> frozenset[str]:
        if node_id in result:
            return result[node_id]
        if node_id in visiting:
            raise ValueError(f"Dependency cycle through node {node_id}")
        visiting.add(node_id)
        found: set[str] = set()
        for dependency in by_id[node_id].depends_on:
            found.add(dependency)
            found |= visit(dependency)
        visiting.discard(node_id)
        result[node_id] = frozenset(found)
        return result[node_id]

    for node in spec.nodes:
        visit(node.id)
    return result


def validate_graph(spec: PlanSpec) -> None:
    ids = [node.id for node in spec.nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("node ids must be unique")
    known = set(ids)
    for node in spec.nodes:
        if node.id in node.depends_on:
            raise ValueError(f"Node {node.id} cannot depend on itself")
        if len(node.depends_on) != len(set(node.depends_on)):
            raise ValueError(f"Node {node.id} has duplicate dependencies")
        unknown = [item for item in node.depends_on if item not in known]
        if unknown:
            raise ValueError(f"Node {node.id} depends on unknown node(s): {', '.join(unknown)}")
    order = ancestors(spec)
    for index, first in enumerate(spec.nodes):
        for second in spec.nodes[index + 1 :]:
            if first.id in order[second.id] or second.id in order[first.id]:
                continue  # ordered by dependency: they never run at the same time
            for left in first.owns:
                for right in second.owns:
                    if patterns_may_overlap(left, right):
                        raise ValueError(
                            f"Nodes {first.id} and {second.id} may run concurrently but their "
                            f"ownership may overlap ({left} vs {right}); add a dependency or "
                            "narrow the patterns"
                        )


def topological_order(spec: PlanSpec) -> list[str]:
    depth = {node_id: len(found) for node_id, found in ancestors(spec).items()}
    position = {node.id: index for index, node in enumerate(spec.nodes)}
    return sorted(depth, key=lambda node_id: (depth[node_id], position[node_id]))


def ready_nodes(
    spec: PlanSpec,
    statuses: Mapping[str, NodeStatus],
    *,
    slots_free: int,
    keep_going: bool = False,
) -> list[str]:
    """Nodes to launch now: dependencies integrated, bounded by free slots."""
    slots = min(slots_free, MAX_CONCURRENCY)
    if slots <= 0:
        return []
    if not keep_going and any(status in PROBLEMS for status in statuses.values()):
        return []
    ready = [
        node.id
        for node in spec.nodes
        if statuses[node.id] == NodeStatus.PENDING
        and all(statuses[dependency] == NodeStatus.INTEGRATED for dependency in node.depends_on)
    ]
    return ready[:slots]


def skipped_nodes(spec: PlanSpec, statuses: Mapping[str, NodeStatus]) -> list[str]:
    """Pending nodes that can never run because an ancestor failed or was cancelled."""
    order = ancestors(spec)
    return [
        node.id
        for node in spec.nodes
        if statuses[node.id] == NodeStatus.PENDING
        and any(statuses[item] in DEAD for item in order[node.id])
    ]


def node_description(spec: PlanNodeSpec) -> str:
    owns = ", ".join(spec.owns)
    return (
        f"{spec.description}\n\nOwnership: you may create or modify only paths matching: "
        f"{owns}. Any change outside these paths fails the task."
    )


def node_status_for_task(state: State) -> NodeStatus:
    return {
        State.COMPLETED: NodeStatus.VERIFIED,
        State.FAILED: NodeStatus.FAILED,
        State.CANCELLED: NodeStatus.CANCELLED,
        State.PAUSED: NodeStatus.PAUSED,
        State.BLOCKED: NodeStatus.BLOCKED,
    }.get(state, NodeStatus.RUNNING)


def derive_plan_status(statuses: Sequence[NodeStatus], *, promoted: bool = False) -> PlanStatus:
    values = set(statuses)
    if promoted:
        return PlanStatus.PROMOTED
    if values == {NodeStatus.INTEGRATED}:
        return PlanStatus.READY
    if values & {NodeStatus.RUNNING, NodeStatus.VERIFIED}:
        return PlanStatus.RUNNING
    for node_status, plan_status in (
        (NodeStatus.FAILED, PlanStatus.FAILED),
        (NodeStatus.CANCELLED, PlanStatus.CANCELLED),
        (NodeStatus.BLOCKED, PlanStatus.BLOCKED),
        (NodeStatus.PAUSED, PlanStatus.PAUSED),
    ):
        if node_status in values:
            return plan_status
    if values == {NodeStatus.PENDING}:
        return PlanStatus.CREATED
    return PlanStatus.PAUSED  # interrupted between nodes; resumable


class PlanNode(Contract):
    spec: PlanNodeSpec
    status: NodeStatus = NodeStatus.PENDING
    task_id: str | None = None
    base_commit: str | None = None
    node_commit: str | None = None
    integrated_commit: str | None = None
    message: str = ""
    # None is a legacy record, resolved and persisted when its task is first created.
    effective_budgets: Budgets | None = None
    effective_max_repairs: int | None = Field(default=None, ge=0, le=10)
    # E2 durable summary index entry, recorded when the node integrates.
    handoff: DependencyHandoff | None = None
    # E2 human plan attestation; validated again at launch and by the engine.
    attestation: PlanAttestation | None = None


class PlanRecord(Contract):
    id: str = Field(default_factory=identity)
    project: Path
    spec: PlanSpec
    # Before E1 node_budgets was a complete replacement, including null limits.
    # New records explicitly use 2; missing legacy metadata must keep that behavior.
    budget_schema_version: Literal[1, 2] = 1
    nodes: list[PlanNode]
    status: PlanStatus = PlanStatus.CREATED
    base_commit: str
    branch: str
    workspace: Path
    head_commit: str
    final_verified: bool = False
    final_verification: list[VerificationResult] = Field(default_factory=list)
    promoted_commit: str | None = None
    message: str = ""
    cancel_requested: bool = False
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)

    def node(self, node_id: str) -> PlanNode:
        for node in self.nodes:
            if node.spec.id == node_id:
                return node
        raise ValueError(f"Unknown plan node: {node_id}")

    def statuses(self) -> dict[str, NodeStatus]:
        return {node.spec.id: node.status for node in self.nodes}

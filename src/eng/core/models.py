import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def now() -> str:
    return datetime.now(UTC).isoformat()


def identity() -> str:
    return uuid4().hex


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class State(StrEnum):
    CREATED = "CREATED"
    CLASSIFYING = "CLASSIFYING"
    PREPARING_CONTEXT = "PREPARING_CONTEXT"
    PLANNING = "PLANNING"
    IMPLEMENTING = "IMPLEMENTING"
    VERIFYING = "VERIFYING"
    REVIEWING = "REVIEWING"
    DEBUGGING = "DEBUGGING"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Role(StrEnum):
    PLANNER = "planner"
    ENGINEER = "engineer"
    VERIFIER = "verifier"
    DEBUGGER = "debugger"
    REVIEWER = "reviewer"


class TaskType(StrEnum):
    CHANGE = "change"
    QUESTION = "question"


class Complexity(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    COMPLEX = "complex"


class Risk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Classification(Contract):
    task_type: TaskType
    complexity: Complexity
    risk: Risk
    reasons: list[str] = Field(default_factory=list)


class ClassificationOverrides(Contract):
    task_type: TaskType | None = None
    complexity: Complexity | None = None
    risk: Risk | None = None


class WorkflowPolicy(Contract):
    max_repairs: int = Field(default=2, ge=0, le=10)


class WorkflowDecision(Contract):
    planner: bool
    reviewer: bool
    approval_required: bool
    max_repairs: int = Field(default=2, ge=0, le=10)


class RoleHandoff(Contract):
    role: Role
    summary: str
    invocation_id: str
    artifact: str | None = None
    verdict: Literal["pass", "changes_requested"] | None = None
    findings: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    root_cause: str | None = None
    changed_files: list[str] = Field(default_factory=list)


class RepairAttempt(Contract):
    number: int = Field(ge=1)
    failure_signature: str
    handoff: RoleHandoff | None = None


class Usage(Contract):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    cache_creation_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cost_source: Literal["reported", "client_estimate", "unknown"] = "unknown"
    source: Literal["provider", "unknown"] = "unknown"


class RoleLimits(Contract):
    """Optional pre-next-call limits within the enclosing task's overall limits."""

    model_calls: int | None = Field(default=None, ge=1, le=100)
    reported_input_tokens: int | None = Field(default=None, gt=0)
    reported_output_tokens: int | None = Field(default=None, gt=0)
    reported_cost_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class Budgets(Contract):
    wall_seconds: float = Field(default=300, gt=0, le=86400)
    provider_seconds: float = Field(default=180, gt=0, le=86400)
    model_calls: int = Field(default=1, ge=1, le=100)
    context_chars: int = Field(default=16000, ge=256, le=1000000)
    reported_input_tokens: int | None = Field(default=None, gt=0)
    reported_output_tokens: int | None = Field(default=None, gt=0)
    reported_cost_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    role_limits: dict[Role, RoleLimits] = Field(default_factory=dict)

    @field_validator("role_limits")
    @classmethod
    def model_roles_only(cls, value: dict[Role, RoleLimits]) -> dict[Role, RoleLimits]:
        if Role.VERIFIER in value:
            raise ValueError("Verifier runs deterministic checks and has no model allocation")
        return value


class PricingRule(Contract):
    """User supplied estimate; rates are USD per million native tokens."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    version: str = Field(min_length=1)
    label: str = Field(min_length=1)
    input_semantics: Literal["inclusive", "exclusive"]
    input_per_million: float = Field(ge=0, allow_inf_nan=False)
    output_per_million: float = Field(ge=0, allow_inf_nan=False)
    cached_input_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cache_creation_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class InvocationRecord(Contract):
    invocation_id: str
    execution_id: str
    task_id: str | None = None
    provider: str
    model: str | None = None
    role: Role
    status: str
    result: "ProviderResult | None" = None


class Check(Contract):
    name: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    argv: list[str] = Field(min_length=1)
    timeout_seconds: float = Field(default=60, gt=0, le=86400)
    required: bool = True
    confirmed: bool = False

    @field_validator("argv")
    @classmethod
    def valid_argv(cls, value: list[str]) -> list[str]:
        if any("\x00" in item for item in value) or not value[0].strip():
            raise ValueError("command must have an executable and contain no NULs")
        return value


BUILTIN_PROVIDERS = frozenset({"fake", "codex", "claude"})
_CREDENTIAL_NAME = re.compile(r"(?:token|secret|password|api.?key|credential|private.?key)", re.I)


class CommandProviderConfig(Contract):
    """A coding CLI attached declaratively: fixed argv, prompt on stdin, no vendor flags in eng.

    The command is trusted project configuration, like a check. It runs in the task
    workspace with a scrubbed environment; only ``env_allow`` credentials are forwarded.
    Token usage and cost stay unknown. Planner and reviewer roles must print the strict
    JSON handoff as their whole stdout, otherwise use the CLI for engineering roles only.
    """

    argv: list[str] = Field(min_length=1)
    model_flag: str | None = None
    env_allow: list[str] = Field(default_factory=list)

    @field_validator("argv")
    @classmethod
    def valid_argv(cls, value: list[str]) -> list[str]:
        if any("\x00" in item for item in value) or not value[0].strip():
            raise ValueError("command must have an executable and contain no NULs")
        return value

    @field_validator("env_allow")
    @classmethod
    def credential_names(cls, names: list[str]) -> list[str]:
        for name in names:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError(f"Invalid environment variable name: {name}")
            if not _CREDENTIAL_NAME.search(name):
                raise ValueError(
                    f"{name} must look like a credential (TOKEN, SECRET, PASSWORD, API_KEY, "
                    "CREDENTIAL or PRIVATE_KEY) so its value is redacted; put settings in argv"
                )
        return names


MAX_ROUTES = 50


class RouteMatch(Contract):
    """Empty lists match anything; a rule matches when every non-empty list matches."""

    task_types: list[TaskType] = Field(default_factory=list)
    complexities: list[Complexity] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    roles: list[Role] = Field(default_factory=list)

    @model_validator(mode="after")
    def model_roles_only(self) -> "RouteMatch":
        if Role.VERIFIER in self.roles:
            raise ValueError("verifier runs checks and cannot be routed to a model")
        return self


class RouteRule(Contract):
    label: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    when: RouteMatch = Field(default_factory=RouteMatch)
    provider: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]*$")
    model: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def valid_target(self) -> "RouteRule":
        if self.provider is None and self.model is None:
            raise ValueError(f"route {self.label} selects neither a provider nor a model")
        if self.model is not None and not self.model.strip():
            raise ValueError(f"route {self.label} has a blank model")
        if self.provider is not None and self.when.roles:
            raise ValueError(
                f"route {self.label}: a provider applies to a whole task; remove `roles`"
            )
        return self


class ProjectConfig(Contract):
    schema_version: Literal[1] = 1
    name: str = "project"
    languages: list[str] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=lambda: ["AGENTS.md"])
    checks: list[Check] = Field(default_factory=list)
    protected_paths: list[str] = Field(
        default_factory=lambda: [
            ".git",
            ".engineering",
            ".env",
            ".env.*",
            "*.pem",
            "*.key",
        ]
    )
    budgets: Budgets = Field(default_factory=Budgets)
    workflow: WorkflowPolicy = Field(default_factory=WorkflowPolicy)
    provider: str = "codex"
    role_models: dict[Role, str] = Field(default_factory=dict)
    pricing: list[PricingRule] = Field(default_factory=list)
    command_providers: dict[str, CommandProviderConfig] = Field(default_factory=dict)
    # E3 explicit routing rules, first match wins; empty keeps E2 selection behaviour.
    routing: list[RouteRule] = Field(default_factory=list, max_length=MAX_ROUTES)

    @field_validator("command_providers")
    @classmethod
    def valid_command_providers(
        cls, providers: dict[str, CommandProviderConfig]
    ) -> dict[str, CommandProviderConfig]:
        for name in providers:
            if not re.fullmatch(r"[a-z][a-z0-9_-]*", name) or name in BUILTIN_PROVIDERS:
                raise ValueError(f"Invalid or reserved provider name: {name!r}")
        return providers

    @field_validator("routing")
    @classmethod
    def unique_routes(cls, rules: list[RouteRule]) -> list[RouteRule]:
        labels = [rule.label for rule in rules]
        if len(labels) != len(set(labels)):
            raise ValueError("routing rule labels must be unique")
        return rules

    @field_validator("role_models")
    @classmethod
    def valid_role_models(cls, models: dict[Role, str]) -> dict[Role, str]:
        if any(not value.strip() for value in models.values()):
            raise ValueError("role model names cannot be blank")
        return models

    @field_validator("pricing")
    @classmethod
    def unique_pricing(cls, rules: list[PricingRule]) -> list[PricingRule]:
        keys = [(rule.provider, rule.model) for rule in rules]
        if len(keys) != len(set(keys)):
            raise ValueError("pricing must have one explicit rule per provider/model")
        return rules

    @field_validator("checks")
    @classmethod
    def unique_checks(cls, checks: list[Check]) -> list[Check]:
        names = [check.name for check in checks]
        if len(names) != len(set(names)):
            raise ValueError("check names must be unique")
        return checks


DIGEST = r"^[0-9a-f]{64}$"
COMMIT = r"^[0-9a-fA-F]{7,64}$"


class PlanAttestation(Contract):
    """Human statement that a plan node's own spec is its plan (E2).

    Created only by the explicit `eng plan attest` CLI action. It binds the node's
    packet-visible scope, the project verification policy and the integration revision
    at which it was granted. Any mismatch falls back to the ordinary model planner; it
    never satisfies review, checks, task approval or ownership.
    """

    id: str = Field(default_factory=identity)
    plan_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    scope_digest: str = Field(pattern=DIGEST)
    policy_digest: str = Field(pattern=DIGEST)
    revision: str = Field(pattern=COMMIT)
    source: Literal["explicit_cli"] = "explicit_cli"
    created_at: str = Field(default_factory=now)


class DependencyHandoff(Contract):
    """Compact typed summary of one integrated plan node, reused by its dependents (E2).

    ``digest`` covers every field except ``stale_files``, which is computed per consumer
    at launch: dependency files changed again between integration and that launch.
    """

    node_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    node_commit: str = Field(pattern=COMMIT)
    integrated_commit: str = Field(pattern=COMMIT)
    summary: str = Field(default="", max_length=1000)
    review_verdict: Literal["pass", "changes_requested"] | None = None
    changed_files: list[str] = Field(default_factory=list, max_length=50)
    files_truncated: bool = False
    interfaces: list[str] = Field(default_factory=list, max_length=20)
    policy_digest: str = Field(pattern=DIGEST)
    digest: str = Field(pattern=DIGEST)
    stale_files: list[str] = Field(default_factory=list, max_length=50)


class TaskSpec(Contract):
    description: str = Field(min_length=1, max_length=64000)
    acceptance: list[str] = Field(min_length=1)
    provider: str = "codex"
    model: str | None = None
    budgets: Budgets = Field(default_factory=Budgets)
    context_paths: list[str] = Field(default_factory=list)
    classification_overrides: ClassificationOverrides = Field(
        default_factory=ClassificationOverrides
    )
    human_approved: bool = False
    # Empty means unrestricted (M0-M5 behaviour). Plan nodes always declare ownership;
    # the engine fails a task that changes any path outside these patterns.
    owned_paths: list[str] = Field(default_factory=list)
    # Start the worktree from this commit instead of the checkout's HEAD (plan nodes
    # start from the integration head so they see their dependencies' integrated work).
    base_commit: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{7,64}$")
    # E2 plan context reuse. Empty/None is the uncached path: packets are unchanged.
    interfaces: list[str] = Field(default_factory=list, max_length=20)
    dependency_handoffs: list[DependencyHandoff] = Field(default_factory=list, max_length=50)
    plan_attestation: PlanAttestation | None = None

    @field_validator("model")
    @classmethod
    def valid_model(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("model cannot be blank")
        return value

    @field_validator("description", "acceptance")
    @classmethod
    def not_blank(cls, value: str | list[str]) -> str | list[str]:
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("description cannot be blank")
        elif any(not item.strip() for item in value):
            raise ValueError("acceptance criteria cannot be blank")
        return value


class Capabilities(Contract):
    kind: Literal["coding_cli", "model_api", "local", "fake"]
    file_editing: bool = False
    tool_execution: bool = False
    structured_output: bool = False
    streaming: bool = False
    session_resumption: bool = False
    prompt_caching: bool = False
    token_reporting: bool = False
    cost_reporting: bool = False
    working_directory_isolation: bool = False
    permission_controls: bool = False
    # Accepts ProviderRequest.model (E3 routing skips model routes otherwise).
    model_selection: bool = False
    context_limit: int | None = None


class ProviderRequest(Contract):
    task_id: str
    execution_id: str
    role: Role = Role.ENGINEER
    workspace: Path
    prompt: str
    timeout_seconds: float = Field(gt=0)
    model: str | None = None


ProviderStatus = Literal["success", "error", "cancelled", "timeout"]
Outcome = Literal["PASS", "FAIL", "SKIPPED", "UNAVAILABLE", "ERROR"]


class InvocationTelemetry(Contract):
    """Measured orchestration data, never a measure of hidden provider context."""

    provider_invoked: bool = False
    packet_chars: int | None = Field(default=None, ge=0)
    packet_utf8_bytes: int | None = Field(default=None, ge=0)
    context_duration_seconds: float | None = Field(default=None, ge=0)
    role_duration_seconds: float | None = Field(default=None, ge=0)


class ProviderResult(Contract):
    status: ProviderStatus
    summary: str = ""
    error_kind: str | None = None
    usage: Usage = Field(default_factory=Usage)
    duration_seconds: float = Field(default=0, ge=0)
    session_id: str | None = None
    # Set only from explicit provider evidence, never copied from requested model.
    actual_model: str | None = Field(default=None, min_length=1, max_length=256)
    telemetry: InvocationTelemetry | None = None


class VerificationResult(Contract):
    check_id: str
    command: list[str]
    environment: str
    exit_code: int | None = None
    duration_seconds: float = Field(default=0, ge=0)
    artifact: str | None = None
    outcome: Outcome
    reason: str | None = None
    required: bool = True


class Task(Contract):
    id: str = Field(default_factory=identity)
    project: Path
    spec: TaskSpec
    config: ProjectConfig
    state: State = State.CREATED
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    workspace: Path | None = None
    base_commit: str | None = None
    execution_id: str | None = None
    checkpoint: Literal[
        "created", "prepared", "planned", "provider_started", "implemented", "verified", "reviewed"
    ] = "created"
    cancel_requested: bool = False
    provider_calls: int = 0
    elapsed_seconds: float = 0
    message: str = ""
    verification: list[VerificationResult] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    classification: Classification | None = None
    workflow: WorkflowDecision | None = None
    handoffs: list[RoleHandoff] = Field(default_factory=list)
    repairs: list[RepairAttempt] = Field(default_factory=list)
    pending_role: Role | None = None
    pending_invocation_id: str | None = None
    pending_model: str | None = None
    next_role: Role | None = None
    planning_completed: bool = False
    review_passed: bool = False
    verified_digest: str | None = None
    review_digest: str | None = None

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class Budgets(Contract):
    wall_seconds: float = Field(default=300, gt=0, le=86400)
    provider_seconds: float = Field(default=180, gt=0, le=86400)
    model_calls: int = Field(default=1, ge=1, le=100)
    context_chars: int = Field(default=16000, ge=256, le=1000000)
    reported_input_tokens: int | None = Field(default=None, gt=0)
    reported_output_tokens: int | None = Field(default=None, gt=0)
    reported_cost_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)


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


class ProviderResult(Contract):
    status: ProviderStatus
    summary: str = ""
    error_kind: str | None = None
    usage: Usage = Field(default_factory=Usage)
    duration_seconds: float = Field(default=0, ge=0)
    session_id: str | None = None


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

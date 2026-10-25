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


class Usage(Contract):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    source: Literal["provider", "unknown"] = "unknown"


class Budgets(Contract):
    wall_seconds: float = Field(default=300, gt=0, le=86400)
    provider_seconds: float = Field(default=180, gt=0, le=86400)
    model_calls: int = Field(default=1, ge=1, le=100)
    context_chars: int = Field(default=16000, ge=256, le=1000000)


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
    provider: str = "codex"

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
    checkpoint: Literal["created", "prepared", "provider_started", "implemented", "verified"] = (
        "created"
    )
    cancel_requested: bool = False
    provider_calls: int = 0
    elapsed_seconds: float = 0
    message: str = ""
    verification: list[VerificationResult] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)

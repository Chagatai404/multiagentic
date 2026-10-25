"""Normalized trigger contracts and deterministic routing; no I/O or external state.

Client hooks (Claude Code, Codex) and the generic ``eng trigger`` command convert their
input into a TriggerEnvelope. Routing is deliberately high precision: a prompt that is not
an explicit ``eng:`` request (or, in adaptive/full mode, a clearly imperative change
request) passes through to the interactive client unchanged.
"""

import hashlib
import json
import re
from enum import StrEnum
from typing import Literal

from pydantic import Field

from eng.core.models import Contract, TaskSpec, TaskType
from eng.core.workflow import classify_task

# A content-derived key (no client turn/prompt id) only deduplicates within this window,
# so a deliberate resubmission later starts a new task.
CONTENT_DEDUP_SECONDS = 120.0


class TriggerOrigin(StrEnum):
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"
    CLI = "cli"


class TriggerMode(StrEnum):
    MANUAL = "manual"  # only explicit eng: requests route
    ADAPTIVE = "adaptive"  # adds high-confidence imperative change requests
    FULL = "full"  # adaptive routing plus stronger verification of routed work


class TriggerAction(StrEnum):
    BYPASS = "bypass"  # pass the prompt through untouched
    ROUTE = "route"  # create an orchestrated task and block the interactive prompt
    DUPLICATE = "duplicate"  # already routed; report the existing task
    REENTRANT = "reentrant"  # fired inside an eng-launched process; never route


class TriggerEnvelope(Contract):
    origin: TriggerOrigin
    event: str = "UserPromptSubmit"
    session_id: str | None = Field(default=None, max_length=512)
    # Claude Code prompt_id or Codex turn_id; preferred idempotency identity when present.
    turn_id: str | None = Field(default=None, max_length=512)
    cwd: str = Field(min_length=1, max_length=4096)
    prompt: str = Field(max_length=64000)
    received_at: str  # ISO-8601 UTC, as produced by eng.core.models.now()


class TriggerDecision(Contract):
    action: TriggerAction
    reason: str
    # Routed task description: the prompt with any eng: marker removed.
    description: str | None = None
    full_verification: bool = False
    task_id: str | None = None


class TriggerRecord(Contract):
    key: str
    origin: TriggerOrigin
    session_id: str | None = None
    prompt_digest: str
    content_keyed: bool  # True when no client turn id was available
    task_id: str | None = None
    status: Literal["claimed", "started", "failed"] = "claimed"
    message: str = ""
    created_at: str
    updated_at: str


_ENG_PREFIX = re.compile(r"^\s*eng:(.*)$", re.IGNORECASE | re.DOTALL)
_IMPERATIVE = re.compile(
    r"^\s*(?:please\s+)?(?:fix|implement|add|create|refactor|update|rename|remove"
    r"|write\s+(?:(?:the|new|more|unit|missing)\s+)*tests?)\b",
    re.IGNORECASE,
)


def prompt_digest(prompt: str) -> str:
    normalized = " ".join(prompt.split()).casefold()
    return hashlib.sha256(normalized.encode()).hexdigest()


def idempotency_key(envelope: TriggerEnvelope) -> tuple[str, bool]:
    """Return (key, content_keyed); turn ids identify a turn, digests only dedupe content."""
    if envelope.turn_id:
        parts = [envelope.origin.value, envelope.session_id or "", "turn", envelope.turn_id]
        content_keyed = False
    else:
        parts = [
            envelope.origin.value,
            envelope.session_id or "",
            "content",
            prompt_digest(envelope.prompt),
        ]
        content_keyed = True
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest(), content_keyed


def _bypass(reason: str) -> TriggerDecision:
    return TriggerDecision(action=TriggerAction.BYPASS, reason=reason)


def route_trigger(
    envelope: TriggerEnvelope, mode: TriggerMode, *, reentrant: bool
) -> TriggerDecision:
    if reentrant:
        return TriggerDecision(
            action=TriggerAction.REENTRANT, reason="Fired inside an eng-launched process"
        )
    explicit = _ENG_PREFIX.match(envelope.prompt)
    if explicit:
        description = explicit.group(1).strip()
        if not description:
            return _bypass("Blank eng: request")
        return TriggerDecision(
            action=TriggerAction.ROUTE,
            reason="Explicit eng: request",
            description=description,
            full_verification=mode == TriggerMode.FULL,
        )
    prompt = envelope.prompt.strip()
    if not prompt:
        return _bypass("Empty prompt")
    if prompt.startswith("/"):
        return _bypass("Slash command")
    if mode == TriggerMode.MANUAL:
        return _bypass("Manual mode routes only eng: requests")
    if classify_task(TaskSpec(description=prompt, acceptance=["passes"])).task_type == (
        TaskType.QUESTION
    ):
        return _bypass("Question or explanation request")
    if _IMPERATIVE.match(prompt) and not prompt.endswith("?") and len(prompt.split()) >= 3:
        return TriggerDecision(
            action=TriggerAction.ROUTE,
            reason="High-confidence imperative change request",
            description=prompt,
            full_verification=mode == TriggerMode.FULL,
        )
    return _bypass("Ambiguous prompt passes through")

import json
from dataclasses import dataclass
from types import MappingProxyType

from eng.core.models import Role, RoleHandoff


@dataclass(frozen=True)
class RoleDefinition:
    role: Role
    instruction: str
    read_only: bool = False
    deterministic: bool = False


class RoleRegistry:
    def __init__(self) -> None:
        self._roles: dict[Role, RoleDefinition] = {}

    def register(self, definition: RoleDefinition, *, replace: bool = False) -> None:
        if definition.role in self._roles and not replace:
            raise ValueError(f"Role already registered: {definition.role}")
        self._roles[definition.role] = definition

    def get(self, role: Role) -> RoleDefinition:
        return self._roles[role]


_BUILTINS = (
    RoleDefinition(
        Role.PLANNER,
        'Plan only. Return exactly JSON with "summary" (string) and '
        '"steps" (nonempty string array). Do not change any file.',
        read_only=True,
    ),
    RoleDefinition(
        Role.ENGINEER,
        "Implement the requested change and summarize the result. Verification runs separately.",
    ),
    RoleDefinition(Role.VERIFIER, "Run deterministic configured checks.", deterministic=True),
    RoleDefinition(
        Role.DEBUGGER,
        "Diagnose the focused failure evidence, make a targeted repair, "
        "and summarize the root cause and changes.",
    ),
    RoleDefinition(
        Role.REVIEWER,
        "Review the current implementation against acceptance criteria. "
        'Return exactly JSON with "summary" (string), "verdict" '
        '("pass" or "changes_requested"), and "findings" (string array). '
        "Pass requires zero findings; changes_requested requires findings. "
        "Do not change any file.",
        read_only=True,
    ),
)
_DEFINITIONS = MappingProxyType({definition.role: definition for definition in _BUILTINS})


def get_role(role: Role, registry: RoleRegistry | None = None) -> RoleDefinition:
    return registry.get(role) if registry is not None else _DEFINITIONS[role]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate handoff key: {key}")
        result[key] = value
    return result


def parse_handoff(
    role: Role,
    summary: str,
    invocation_id: str,
    artifact: str | None = None,
) -> RoleHandoff:
    if role not in (Role.PLANNER, Role.REVIEWER):
        return RoleHandoff(
            role=role, summary=summary, invocation_id=invocation_id, artifact=artifact
        )
    payload = json.loads(summary, object_pairs_hook=_unique_object)
    expected = {"summary", "steps"} if role == Role.PLANNER else {"summary", "verdict", "findings"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("Handoff must contain exactly the requested JSON fields")
    if not isinstance(payload["summary"], str) or not payload["summary"].strip():
        raise ValueError("Handoff summary must be a nonempty string")
    items = payload["steps"] if role == Role.PLANNER else payload["findings"]
    if not isinstance(items, list) or any(not isinstance(x, str) or not x.strip() for x in items):
        raise ValueError("Handoff items must be nonempty strings")
    if role == Role.PLANNER and not items:
        raise ValueError("Planner must supply at least one step")
    if role == Role.REVIEWER:
        if payload["verdict"] not in ("pass", "changes_requested"):
            raise ValueError("Reviewer must supply an explicit verdict")
        if (payload["verdict"] == "pass") != (not items):
            raise ValueError("Review verdict and findings disagree")
    return RoleHandoff(
        role=role,
        invocation_id=invocation_id,
        artifact=artifact,
        **payload,
    )

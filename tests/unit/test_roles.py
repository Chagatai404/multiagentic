import json
from pathlib import Path

import pytest

from eng.agents import RoleDefinition, RoleRegistry, get_role, parse_handoff
from eng.context.packet import build_packet
from eng.core.models import Budgets, ProjectConfig, Role, Task, TaskSpec


@pytest.mark.parametrize("role", list(Role))
def test_builtin_roles(role: Role) -> None:
    assert get_role(role).role == role
    assert get_role(role).deterministic == (role == Role.VERIFIER)


def test_registry_is_explicitly_extensible() -> None:
    registry = RoleRegistry()
    role = RoleDefinition(Role.ENGINEER, "custom")
    registry.register(role)
    assert registry.get(Role.ENGINEER) == role
    with pytest.raises(ValueError):
        registry.register(role)


@pytest.mark.parametrize(
    "payload",
    [
        'prose {"summary":"ok","steps":["one"]}',
        '```json\n{"summary":"ok","steps":["one"]}\n```',
        '{"summary":"ok","steps":[]}',
        '{"summary":"ok","steps":[1]}',
        '{"summary":"ok","steps":["one"],"extra":true}',
        '{"summary":"ok","summary":"other","steps":["one"]}',
    ],
)
def test_planner_rejects_unstructured_handoffs(payload: str) -> None:
    with pytest.raises(ValueError):
        parse_handoff(Role.PLANNER, payload, "invocation")


@pytest.mark.parametrize(
    "verdict,findings",
    [
        ("pass", ["bug"]),
        ("changes_requested", []),
        (None, []),
        ("PASS", []),
    ],
)
def test_reviewer_requires_consistent_verdict(verdict: str | None, findings: list[str]) -> None:
    with pytest.raises(ValueError):
        parse_handoff(
            Role.REVIEWER,
            json.dumps(
                {
                    "summary": "Review",
                    "verdict": verdict,
                    "findings": findings,
                }
            ),
            "call",
        )


def test_typed_handoffs() -> None:
    plan = parse_handoff(Role.PLANNER, '{"summary":"Plan","steps":["implement"]}', "p")
    assert plan.steps == ["implement"]
    assert parse_handoff(Role.ENGINEER, "Changed code", "e").summary == "Changed code"


def test_packet_bounds_and_redacts_focused_evidence(repo: Path) -> None:
    task = Task(
        project=repo,
        workspace=repo,
        config=ProjectConfig(),
        spec=TaskSpec(
            description="Fix assertion",
            acceptance=["checks pass"],
            budgets=Budgets(context_chars=1800),
        ),
    )
    packet = build_packet(
        task, Role.DEBUGGER, evidence=f"{repo} password=veryprivatevalue\n" + "failure\n" * 900
    )
    assert len(packet) <= 1800
    assert "veryprivatevalue" not in packet
    assert str(repo) not in packet
    assert "Focused failure evidence" in packet
    assert "Fix assertion" in build_packet(task)

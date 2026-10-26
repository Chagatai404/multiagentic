"""E4: opt-in repair headroom admission and unchanged-repair pauses."""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from eng.core.engine import Engine
from eng.core.models import (
    Budgets,
    ClassificationOverrides,
    ProviderRequest,
    ProviderResult,
    Risk,
    Role,
    RoleLimits,
    State,
    Task,
    TaskSpec,
)
from eng.projects.config import load_config
from eng.providers.fake import FakeProvider
from eng.storage.store import Store


class RejectOnceProvider(FakeProvider):
    """Reviewer requests changes on its first call and passes afterwards."""

    def __init__(self, changes: dict[str, str]) -> None:
        super().__init__(changes)
        self.reviews = 0

    async def execute(
        self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
    ) -> ProviderResult:
        if request.role == Role.REVIEWER:
            self.reviews += 1
            if self.reviews == 1:
                summary = {"summary": "No", "verdict": "changes_requested", "findings": ["Fix"]}
                return ProviderResult(status="success", summary=json.dumps(summary))
        return await super().execute(request, artifact_dir, cancelled)


def run(
    repo: Path,
    provider: FakeProvider,
    *,
    calls: int,
    risk: Risk | None = None,
    role_limits: dict[Role, RoleLimits] | None = None,
    **workflow: Any,
) -> tuple[Store, Task]:
    config = load_config(repo)
    config.workflow = config.workflow.model_copy(update=workflow)
    store = Store(repo)
    task = Task(
        project=repo,
        spec=TaskSpec(
            description="Fix the answer",
            acceptance=["answer is 42"],
            provider="fake",
            budgets=Budgets(model_calls=calls, role_limits=role_limits or {}),
            classification_overrides=ClassificationOverrides(risk=risk),
        ),
        config=config,
    )
    store.create(task)
    return store, asyncio.run(Engine(store, provider).execute(task.id))


def roles(store: Store, task: Task) -> list[Role]:
    return [record.role for record in store.invocations(task.id)]


def check_rounds(store: Store, task: Task) -> int:
    return len(store.verification_results(task.id))  # one configured check per round


def test_unchanged_check_repair_pauses_without_rechecking_and_resumes(repo: Path) -> None:
    store, task = run(repo, FakeProvider(), calls=3, stop_unchanged_repairs=True)
    assert task.state == State.PAUSED and "no workspace changes" in task.message
    assert roles(store, task) == [Role.ENGINEER, Role.DEBUGGER]
    assert check_rounds(store, task) == 1
    assert any(e["kind"] == "repair_unchanged" for e in store.events(task.id))
    # A human fixes the workspace; resume re-runs checks without another model call.
    assert task.workspace is not None
    (task.workspace / "answer.txt").write_text("42", encoding="utf-8")
    resumed = asyncio.run(Engine(store, FakeProvider()).execute(task.id, resume=True))
    assert resumed.state == State.COMPLETED
    assert roles(store, resumed) == [Role.ENGINEER, Role.DEBUGGER]


def test_unchanged_review_repair_saves_the_repeat_review(repo: Path) -> None:
    fix = {"answer.txt": "42"}
    store, task = run(
        repo, RejectOnceProvider(fix), calls=5, risk=Risk.MEDIUM, stop_unchanged_repairs=True
    )
    assert task.state == State.PAUSED and "no workspace changes" in task.message
    assert roles(store, task) == [Role.ENGINEER, Role.REVIEWER, Role.DEBUGGER]
    assert not task.review_passed


def test_unchanged_repair_default_keeps_previous_behaviour(repo: Path) -> None:
    fix = {"answer.txt": "42"}
    store, task = run(repo, RejectOnceProvider(fix), calls=5, risk=Risk.MEDIUM)
    assert task.state == State.COMPLETED
    assert roles(store, task) == [Role.ENGINEER, Role.REVIEWER, Role.DEBUGGER, Role.REVIEWER]


def test_headroom_blocks_a_check_repair_whose_review_cannot_run(repo: Path) -> None:
    store, task = run(repo, FakeProvider(), calls=2, risk=Risk.MEDIUM, repair_headroom=True)
    assert task.state == State.BLOCKED
    assert "repair needs 2 model calls (debugger and required review); 1 remain" in task.message
    assert roles(store, task) == [Role.ENGINEER] and task.repairs == []
    # Without the opt-in, the debugger spends the last call and review still cannot run.
    store, default = run(repo, FakeProvider(), calls=2, risk=Risk.MEDIUM)
    assert roles(store, default) == [Role.ENGINEER, Role.DEBUGGER]
    assert default.state != State.COMPLETED


def test_headroom_keeps_review_repairs_durable_and_respects_role_allocations(
    repo: Path,
) -> None:
    store, task = run(
        repo,
        RejectOnceProvider({"answer.txt": "42"}),
        calls=6,
        risk=Risk.MEDIUM,
        role_limits={Role.REVIEWER: RoleLimits(model_calls=1)},
        repair_headroom=True,
    )
    assert task.state == State.PAUSED
    assert "role reviewer CLI invocation allocation exhausted" in task.message
    assert roles(store, task) == [Role.ENGINEER, Role.REVIEWER]
    # The repair is recorded before the debugger, so an extension runs it next.
    assert len(task.repairs) == 1 and task.next_role == Role.DEBUGGER


def test_headroom_admits_a_repair_that_can_finish(repo: Path) -> None:
    store, task = run(
        repo,
        RejectOnceProvider({"answer.txt": "42"}),
        calls=4,
        risk=Risk.MEDIUM,
        repair_headroom=True,
        stop_unchanged_repairs=True,
    )
    # The engineer already fixed the answer; the reviewer's requested repair changes
    # nothing, so the unchanged-repair pause applies before a second review.
    assert roles(store, task) == [Role.ENGINEER, Role.REVIEWER, Role.DEBUGGER]
    assert task.state == State.PAUSED

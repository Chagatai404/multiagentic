import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from eng.core.engine import Engine
from eng.core.models import (
    Budgets,
    ClassificationOverrides,
    Complexity,
    ProviderRequest,
    ProviderResult,
    Risk,
    Role,
    State,
    Task,
    TaskSpec,
)
from eng.execution.workspace import prepare
from eng.projects.config import load_config
from eng.providers.fake import FakeProvider
from eng.storage.store import Store


def make_task(
    repo: Path,
    store: Store,
    *,
    calls: int = 5,
    complex: bool = False,
    risk: Risk | None = None,
    approved: bool = False,
) -> Task:
    task = Task(
        project=repo,
        config=load_config(repo),
        spec=TaskSpec(
            description="Fix answer",
            acceptance=["answer is 42"],
            provider="fake",
            budgets=Budgets(model_calls=calls),
            human_approved=approved,
            classification_overrides=ClassificationOverrides(
                complexity=Complexity.COMPLEX if complex else None,
                risk=risk,
            ),
        ),
    )
    store.create(task)
    return task


class SequenceProvider(FakeProvider):
    def __init__(self, answers: list[str], reviews: list[str] | None = None) -> None:
        super().__init__()
        self.answers = iter(answers)
        self.reviews = iter(reviews or [])
        self.roles: list[Role] = []

    async def execute(
        self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
    ) -> ProviderResult:
        self.roles.append(request.role)
        if request.role in {Role.ENGINEER, Role.DEBUGGER}:
            (request.workspace / "answer.txt").write_text(next(self.answers))
            return ProviderResult(status="success", summary="Updated answer")
        if request.role == Role.REVIEWER:
            summary = next(
                self.reviews,
                json.dumps(
                    {"verdict": "pass", "findings": [], "summary": "Reviewed independently"}
                ),
            )
            return ProviderResult(status="success", summary=summary)
        return await super().execute(request, artifact_dir, cancelled)


def test_complex_plan_engineer_review_and_distinct_invocations(repo: Path) -> None:
    with_store = Store(repo)
    task = make_task(repo, with_store, complex=True)
    provider = SequenceProvider(["42"])
    result = asyncio.run(Engine(with_store, provider).execute(task.id))
    assert result.state == State.COMPLETED, result.message
    assert provider.roles == [Role.PLANNER, Role.ENGINEER, Role.REVIEWER]
    assert result.planning_completed and result.review_passed
    assert result.verified_digest == result.review_digest
    rows = with_store.connection.execute("SELECT * FROM invocations").fetchall()
    assert len(rows) == 3 and len({row["invocation_id"] for row in rows}) == 3
    assert {row["status"] for row in rows} == {"success"}
    with_store.close()


def test_debugger_repairs_and_keeps_all_check_logs(repo: Path) -> None:
    store = Store(repo)
    task = make_task(repo, store)
    provider = SequenceProvider(["41", "42"])
    result = asyncio.run(Engine(store, provider).execute(task.id))
    assert result.state == State.COMPLETED, result.message
    assert provider.roles == [Role.ENGINEER, Role.DEBUGGER]
    assert len(result.repairs) == 1 and result.repairs[0].handoff is not None
    logs = list((repo / ".engineering/artifacts" / task.id).rglob("answer.log"))
    assert len(logs) == 2 and "AssertionError" in logs[0].read_text()
    store.close()


def test_identical_failure_stops_before_second_debugger(repo: Path) -> None:
    store = Store(repo)
    task = make_task(repo, store)
    provider = SequenceProvider(["41", "41", "42"])
    result = asyncio.run(Engine(store, provider).execute(task.id))
    assert result.state == State.BLOCKED, result.message
    assert "identical" in result.message
    assert len(result.repairs) == 1 and result.provider_calls == 2
    store.close()


def test_distinct_failure_same_check_allows_second_repair(repo: Path) -> None:
    store = Store(repo)
    task = make_task(repo, store)
    task.config.checks[0].argv = [
        "{python}",
        "-c",
        "from pathlib import Path; x=Path('answer.txt').read_text(); assert x=='42', x",
    ]
    store.checkpoint(task)
    provider = SequenceProvider(["first failure", "second failure", "42"])
    result = asyncio.run(Engine(store, provider).execute(task.id))
    assert result.state == State.COMPLETED, result.message
    assert len(result.repairs) == 2 and result.provider_calls == 3
    assert result.repairs[0].failure_signature != result.repairs[1].failure_signature
    store.close()


def test_review_rejection_repairs_then_checks_and_reviews_again(repo: Path) -> None:
    store = Store(repo)
    task = make_task(repo, store, risk=Risk.MEDIUM)
    rejection = json.dumps(
        {
            "summary": "Fix style",
            "verdict": "changes_requested",
            "findings": ["Use the expected answer"],
        }
    )
    provider = SequenceProvider(["42", "42"], [rejection])
    result = asyncio.run(Engine(store, provider).execute(task.id))
    assert result.state == State.COMPLETED, result.message
    assert provider.roles == [Role.ENGINEER, Role.REVIEWER, Role.DEBUGGER, Role.REVIEWER]
    assert len(result.repairs) == 1
    store.close()


def test_review_rejection_at_budget_pauses_with_durable_repair(repo: Path) -> None:
    class Recording(SequenceProvider):
        debugger_prompt = ""

        async def execute(
            self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
        ) -> ProviderResult:
            if request.role == Role.DEBUGGER:
                self.debugger_prompt = request.prompt
            return await super().execute(request, artifact_dir, cancelled)

    store = Store(repo)
    task = make_task(repo, store, calls=2, risk=Risk.MEDIUM)
    rejection = json.dumps(
        {
            "summary": "Fix style",
            "verdict": "changes_requested",
            "findings": ["Use the expected answer"],
        }
    )
    provider = Recording(["42", "42"], [rejection])
    result = asyncio.run(Engine(store, provider).execute(task.id))
    assert result.state == State.PAUSED and result.next_role == Role.DEBUGGER, result.message
    assert len(result.repairs) == 1 and result.repairs[0].handoff is None
    result.spec.budgets.model_calls += 1
    store.checkpoint(result)
    result = asyncio.run(Engine(store, provider).execute(task.id, resume=True))
    # The extension goes to the pending repair, which still sees the review findings.
    assert provider.roles == [Role.ENGINEER, Role.REVIEWER, Role.DEBUGGER]
    assert "Use the expected answer" in provider.debugger_prompt
    assert result.state == State.PAUSED and result.next_role == Role.REVIEWER, result.message
    result.spec.budgets.model_calls += 1
    store.checkpoint(result)
    result = asyncio.run(Engine(store, provider).execute(task.id, resume=True))
    assert result.state == State.COMPLETED, result.message
    assert provider.roles[-1] == Role.REVIEWER and len(result.repairs) == 1
    store.close()


def test_malformed_review_blocks_without_repair(repo: Path) -> None:
    store = Store(repo)
    task = make_task(repo, store, risk=Risk.MEDIUM)
    result = asyncio.run(Engine(store, SequenceProvider(["42"], ["looks good"])).execute(task.id))
    assert result.state == State.BLOCKED, result.message
    assert not result.repairs and not result.review_passed
    store.close()


def test_high_risk_pauses_before_workspace_or_call(repo: Path) -> None:
    store = Store(repo)
    task = make_task(repo, store, risk=Risk.HIGH)
    result = asyncio.run(Engine(store, FakeProvider()).execute(task.id))
    assert result.state == State.PAUSED and result.workspace is None
    assert result.provider_calls == 0 and "approve" in result.message
    result.spec.human_approved = True
    store.checkpoint(result)
    approved = asyncio.run(Engine(store, SequenceProvider(["42"])).execute(task.id, resume=True))
    assert approved.state == State.COMPLETED, approved.message
    store.close()


@pytest.mark.parametrize("role", [Role.PLANNER, Role.ENGINEER, Role.DEBUGGER, Role.REVIEWER])
def test_unknown_role_never_replays_verify_only_never_models(repo: Path, role: Role) -> None:
    store = Store(repo)
    task = make_task(
        repo,
        store,
        complex=role == Role.PLANNER,
        risk=Risk.MEDIUM if role == Role.REVIEWER else None,
    )
    prepare(task)
    assert task.workspace is not None
    (task.workspace / "answer.txt").write_text("42")
    task.state = State.PAUSED
    task.checkpoint = "provider_started"
    task.pending_role = role
    task.pending_invocation_id = "unknown-call"
    task.provider_calls = 1
    store.checkpoint(task)
    provider = SequenceProvider([])
    engine = Engine(store, provider)
    result = asyncio.run(engine.execute(task.id, resume=True))
    assert result.state == State.PAUSED and not provider.roles
    verified = asyncio.run(engine.execute(task.id, resume=True, verify_only=True))
    assert not provider.roles and verified.provider_calls == 1
    if role in {Role.PLANNER, Role.REVIEWER}:
        assert verified.state == State.PAUSED, verified.message
        assert verified.next_role == role
        if role == Role.REVIEWER:
            resumed = asyncio.run(engine.execute(task.id, resume=True))
            assert resumed.state == State.COMPLETED, resumed.message
            assert provider.roles == [Role.REVIEWER]
    else:
        assert verified.state == State.COMPLETED, verified.message
    store.close()


def test_required_review_budget_pause_and_extension(repo: Path) -> None:
    store = Store(repo)
    task = make_task(repo, store, calls=1, risk=Risk.MEDIUM)
    provider = SequenceProvider(["42"])
    result = asyncio.run(Engine(store, provider).execute(task.id))
    assert result.state == State.PAUSED and result.next_role == Role.REVIEWER
    verified = asyncio.run(Engine(store, provider).execute(task.id, resume=True, verify_only=True))
    assert verified.state == State.PAUSED and provider.roles == [Role.ENGINEER]
    verified.spec.budgets.model_calls += 1
    store.checkpoint(verified)
    result = asyncio.run(Engine(store, provider).execute(task.id, resume=True))
    assert result.state == State.COMPLETED, result.message
    assert provider.roles == [Role.ENGINEER, Role.REVIEWER]
    store.close()


def test_unexpected_provider_error_preserves_unknown_outcome(repo: Path) -> None:
    class CrashingProvider(FakeProvider):
        async def execute(
            self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
        ) -> ProviderResult:
            (request.workspace / "answer.txt").write_text("42")
            raise RuntimeError("transport disappeared after edit")

    store = Store(repo)
    task = make_task(repo, store)
    result = asyncio.run(Engine(store, CrashingProvider()).execute(task.id))
    assert result.state == State.PAUSED and result.checkpoint == "provider_started"
    provider = SequenceProvider([])
    resumed = asyncio.run(Engine(store, provider).execute(task.id, resume=True))
    assert resumed.state == State.PAUSED and not provider.roles
    verified = asyncio.run(Engine(store, provider).execute(task.id, resume=True, verify_only=True))
    assert verified.state == State.COMPLETED and not provider.roles
    store.close()


def test_changed_paths_escalate_approval_before_acceptance(repo: Path) -> None:
    class SensitiveProvider(SequenceProvider):
        async def execute(
            self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
        ) -> ProviderResult:
            result = await super().execute(request, artifact_dir, cancelled)
            if request.role == Role.ENGINEER:
                (request.workspace / "auth.py").write_text("enabled = True")
            return result

    store = Store(repo)
    task = make_task(repo, store)
    task.config.checks[0].argv = [
        "{python}",
        "-c",
        "from pathlib import Path; Path('checked.marker').write_text('ran'); "
        "assert Path('answer.txt').read_text() == '42'",
    ]
    store.checkpoint(task)
    provider = SensitiveProvider(["42"])
    result = asyncio.run(Engine(store, provider).execute(task.id))
    assert result.state == State.PAUSED, result.message
    assert result.classification is not None and result.classification.risk == Risk.HIGH
    assert result.workflow is not None and result.workflow.approval_required
    assert provider.roles == [Role.ENGINEER]
    assert not result.verification
    assert result.workspace is not None
    assert not (result.workspace / "checked.marker").exists()
    result.spec.human_approved = True
    store.checkpoint(result)
    resumed = asyncio.run(Engine(store, provider).execute(task.id, resume=True))
    assert resumed.state == State.COMPLETED, resumed.message
    assert provider.roles == [Role.ENGINEER, Role.REVIEWER]
    assert (result.workspace / "checked.marker").read_text() == "ran"
    store.close()


def test_mutating_reviewer_can_never_complete(repo: Path) -> None:
    class MutatingProvider(SequenceProvider):
        async def execute(
            self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
        ) -> ProviderResult:
            result = await super().execute(request, artifact_dir, cancelled)
            if request.role == Role.REVIEWER:
                (request.workspace / "answer.txt").write_text("43")
            return result

    store = Store(repo)
    task = make_task(repo, store, risk=Risk.MEDIUM)
    result = asyncio.run(Engine(store, MutatingProvider(["42"])).execute(task.id))
    assert result.state == State.FAILED and "role_mutation" in result.message
    assert not result.review_passed
    assert result.workspace is not None and (result.workspace / "answer.txt").read_text() == "42"
    store.close()


def test_two_distinct_repairs_exhaust_durable_limit(repo: Path) -> None:
    store = Store(repo)
    task = make_task(repo, store)
    task.config.checks[0].argv = [
        "{python}",
        "-c",
        "from pathlib import Path; x=Path('answer.txt').read_text(); assert x=='42', x",
    ]
    store.checkpoint(task)
    provider = SequenceProvider(["first", "second", "third", "42"])
    result = asyncio.run(Engine(store, provider).execute(task.id))
    assert result.state == State.BLOCKED and "limit" in result.message
    assert len(result.repairs) == 2 and result.provider_calls == 3
    resumed = asyncio.run(Engine(store, provider).execute(task.id, resume=True))
    assert resumed.state == State.BLOCKED and resumed.provider_calls == 3
    assert len(store.load(task.id).repairs) == 2
    store.close()


@pytest.mark.parametrize("many_changed", [False, True])
def test_changed_risk_cannot_hide_beyond_classifier_path_bound(
    repo: Path,
    many_changed: bool,
) -> None:
    store = Store(repo)
    task = make_task(repo, store)
    if not many_changed:
        task.spec.context_paths = [f"benign-{number}.txt" for number in range(100)]
    task.config.checks[0].argv = [
        "{python}",
        "-c",
        "from pathlib import Path; Path('checked.marker').write_text('ran')",
    ]
    store.checkpoint(task)
    edits = {"answer.txt": "42", "auth.py": "enabled = True"}
    if many_changed:
        edits.update({f"a{number:03d}.txt": "benign" for number in range(101)})
    result = asyncio.run(Engine(store, FakeProvider(edits)).execute(task.id))
    assert result.state == State.PAUSED, result.message
    assert result.classification is not None and result.classification.risk == Risk.HIGH
    assert result.workflow is not None and result.workflow.approval_required
    assert result.workspace is not None
    assert not result.verification and not (result.workspace / "checked.marker").exists()
    assert result.provider_calls == 1
    store.close()


def test_initial_context_risk_beyond_classifier_bound_prevents_first_call(repo: Path) -> None:
    store = Store(repo)
    task = make_task(repo, store)
    task.spec.context_paths = [f"benign-{number}.txt" for number in range(100)] + ["auth.py"]
    store.checkpoint(task)
    result = asyncio.run(Engine(store, FakeProvider({"answer.txt": "42"})).execute(task.id))
    assert result.state == State.PAUSED, result.message
    assert result.classification is not None and result.classification.risk == Risk.HIGH
    assert result.provider_calls == 0 and result.workspace is None
    store.close()

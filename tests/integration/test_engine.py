import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from eng.core.engine import Engine
from eng.core.models import ProviderRequest, ProviderResult, State, Task, TaskSpec
from eng.execution.workspace import git, prepare
from eng.projects.config import load_config
from eng.providers.fake import FakeProvider
from eng.storage.store import Store


def task_for(repo: Path, store: Store) -> Task:
    task = Task(
        project=repo,
        config=load_config(repo),
        spec=TaskSpec(description="Fix answer", acceptance=["answer is 42"], provider="fake"),
    )
    store.create(task)
    return task


def test_real_worktree_fix_verify_evidence_and_process_boundary(repo: Path) -> None:
    before = git(repo, "rev-parse", "HEAD")
    baseline = subprocess.run([sys.executable, "check.py"], cwd=repo, capture_output=True)
    assert baseline.returncode != 0
    store = Store(repo)
    task = task_for(repo, store)
    result = asyncio.run(Engine(store, FakeProvider({"answer.txt": "42"})).execute(task.id))
    assert result.state == State.COMPLETED, result.message
    assert result.verification[0].outcome == "PASS"
    assert (repo / "answer.txt").read_text() == "41"
    assert git(repo, "rev-parse", "HEAD") == before
    assert git(repo, "status", "--porcelain") == ""
    assert result.workspace != repo
    artifacts = repo / ".engineering/artifacts" / task.id / str(result.execution_id)
    assert (artifacts / "events.jsonl").is_file()
    assert (artifacts / "changes.diff").is_file()
    assert (artifacts / "checks/answer.log").is_file()
    store.close()
    inspected = subprocess.run(
        [sys.executable, "-m", "eng", "status", task.id, "-p", str(repo)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert inspected.returncode == 0, inspected.stderr
    assert json.loads(inspected.stdout)["task"]["state"] == "COMPLETED"


def test_failing_verification_blocks_and_can_resume_without_model(repo: Path) -> None:
    store = Store(repo)
    task = task_for(repo, store)
    engine = Engine(store, FakeProvider())
    failed = asyncio.run(engine.execute(task.id))
    assert failed.state == State.BLOCKED
    assert failed.verification[0].outcome == "FAIL"
    assert failed.workspace is not None
    (failed.workspace / "answer.txt").write_text("42")
    result = asyncio.run(engine.execute(task.id, resume=True))
    assert result.state == State.COMPLETED
    assert result.provider_calls == 1
    assert result.execution_id != failed.execution_id
    store.close()


def test_unconfirmed_check_never_completes(repo: Path) -> None:
    store = Store(repo)
    task = task_for(repo, store)
    task.config.checks[0].confirmed = False
    store.checkpoint(task)
    result = asyncio.run(Engine(store, FakeProvider({"answer.txt": "42"})).execute(task.id))
    assert result.state == State.BLOCKED
    assert result.verification[0].outcome == "SKIPPED"
    store.close()


def test_protected_config_changes_fail_before_verification(repo: Path) -> None:
    store = Store(repo)
    task = task_for(repo, store)
    provider = FakeProvider({".engineering/project.yaml": "checks: []", "answer.txt": "42"})
    result = asyncio.run(Engine(store, provider).execute(task.id))
    assert result.state == State.FAILED
    assert "Protected" in result.message
    assert not result.verification
    store.close()


def test_crash_checkpoint_requires_explicit_verification_and_never_replays(repo: Path) -> None:
    store = Store(repo)
    task = task_for(repo, store)
    for state in [State.CLASSIFYING, State.PREPARING_CONTEXT]:
        store.transition(task, state)
    prepare(task)
    store.transition(task, State.IMPLEMENTING)
    task.checkpoint = "provider_started"
    task.provider_calls = 1
    store.checkpoint(task)
    assert task.workspace is not None
    (task.workspace / "answer.txt").write_text("42")
    store.close()  # simulate process boundary while invocation outcome is uncertain
    store = Store(repo)
    engine = Engine(store, FakeProvider({"answer.txt": "WRONG IF REPLAYED"}))
    paused = asyncio.run(engine.execute(task.id, resume=True))
    assert paused.state == State.PAUSED
    assert "unknown" in paused.message
    result = asyncio.run(engine.execute(task.id, resume=True, verify_only=True))
    assert result.state == State.COMPLETED
    assert result.provider_calls == 1
    store.close()


def test_missing_workspace_and_dirty_source_fail_safely(repo: Path) -> None:
    store = Store(repo)
    task = task_for(repo, store)
    (repo / "untracked.txt").write_text("preserve me")
    result = asyncio.run(Engine(store, FakeProvider()).execute(task.id))
    assert result.state == State.FAILED
    assert "clean" in result.message
    assert (repo / "untracked.txt").read_text() == "preserve me"
    assert result.provider_calls == 0
    store.close()


def test_cancel_from_another_connection_stops_active_task(repo: Path) -> None:
    class SlowProvider(FakeProvider):
        async def execute(
            self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
        ) -> ProviderResult:
            other = Store(repo)
            other.cancel(request.task_id)
            other.close()
            assert cancelled()
            return ProviderResult(status="cancelled")

    store = Store(repo)
    task = task_for(repo, store)
    result = asyncio.run(Engine(store, SlowProvider()).execute(task.id))
    assert result.state == State.CANCELLED
    assert result.workspace is not None and result.workspace.exists()
    assert store.load(task.id).cancel_requested
    store.close()


def test_budget_exhaustion_preserves_checkpoint(repo: Path) -> None:
    store = Store(repo)
    task = task_for(repo, store)
    task.elapsed_seconds = task.spec.budgets.wall_seconds
    store.checkpoint(task)
    result = asyncio.run(Engine(store, FakeProvider()).execute(task.id))
    assert result.state == State.PAUSED
    assert result.provider_calls == 0
    resumed = asyncio.run(Engine(store, FakeProvider()).execute(task.id, resume=True))
    assert resumed.state == State.PAUSED  # repeated exhaustion must not turn into FAILED
    assert resumed.provider_calls == 0
    store.close()


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("ENG_LIVE_CODEX") != "1",
    reason="Set ENG_LIVE_CODEX=1 for a paid bounded smoke test",
)
def test_live_codex_repairs_fixture(repo: Path) -> None:
    from eng.providers.codex import CodexProvider

    store = Store(repo)
    task = Task(
        project=repo,
        config=load_config(repo),
        spec=TaskSpec(
            description=(
                "Change only answer.txt to contain exactly 42 with no newline. "
                "Do not run commands or tools except a file edit."
            ),
            acceptance=["check.py passes and answer.txt contains exactly 42"],
            provider="codex",
        ),
    )
    task.spec.budgets.wall_seconds = 120
    task.spec.budgets.provider_seconds = 90
    store.create(task)
    result = asyncio.run(Engine(store, CodexProvider()).execute(task.id))
    print(result.model_dump_json())
    assert result.state == State.COMPLETED, result.message
    assert result.provider_calls == 1
    store.close()

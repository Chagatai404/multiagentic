import asyncio
import subprocess
from pathlib import Path

from eng.core.engine import Engine
from eng.core.models import State, Task, TaskSpec
from eng.execution.workspace import changed_paths, git, prepare
from eng.projects.config import load_config
from eng.providers.fake import FakeProvider
from eng.storage.store import Store


def run(repo: Path, changes: dict[str, str], owned: list[str]) -> Task:
    store = Store(repo)
    task = Task(
        project=repo,
        config=load_config(repo),
        spec=TaskSpec(
            description="Fix answer", acceptance=["42"], provider="fake", owned_paths=owned
        ),
    )
    store.create(task)
    result = asyncio.run(Engine(store, FakeProvider(changes)).execute(task.id))
    store.close()
    return result


def test_changes_inside_ownership_complete(repo: Path) -> None:
    assert run(repo, {"answer.txt": "42"}, ["answer.txt"]).state == State.COMPLETED


def test_changes_outside_ownership_fail_before_verification(repo: Path) -> None:
    task = run(repo, {"answer.txt": "42", "extra.txt": "x"}, ["answer.txt"])
    assert task.state == State.FAILED
    assert "outside ownership: extra.txt" in task.message
    assert task.verification == []  # failed before any check ran


def test_empty_ownership_is_unrestricted(repo: Path) -> None:
    assert run(repo, {"answer.txt": "42", "extra.txt": "x"}, []).state == State.COMPLETED


def test_both_sides_of_a_rename_are_visible(repo: Path) -> None:
    store = Store(repo)
    task = Task(
        project=repo, config=load_config(repo), spec=TaskSpec(description="x", acceptance=["y"])
    )
    store.create(task)
    workspace = prepare(task)
    assert task.base_commit is not None
    git(workspace, "mv", "answer.txt", "moved.txt")
    assert {"answer.txt", "moved.txt"} <= set(changed_paths(workspace, task.base_commit))
    store.close()


def test_base_commit_starts_the_worktree_from_that_commit(repo: Path) -> None:
    first = git(repo, "rev-parse", "HEAD")
    (repo / "later.txt").write_text("later", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "later")
    store = Store(repo)
    task = Task(
        project=repo,
        config=load_config(repo),
        spec=TaskSpec(description="x", acceptance=["y"], base_commit=first),
    )
    store.create(task)
    workspace = prepare(task)
    assert task.base_commit == first and not (workspace / "later.txt").exists()
    bad = Task(
        project=repo,
        config=load_config(repo),
        spec=TaskSpec(description="x", acceptance=["y"], base_commit="deadbeefdeadbeef"),
    )
    store.create(bad)
    try:
        prepare(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown base commit must be refused")
    store.close()

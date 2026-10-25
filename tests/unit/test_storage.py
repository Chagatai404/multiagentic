from pathlib import Path

import pytest

from eng.core.models import State, Task, TaskSpec
from eng.projects.config import load_config
from eng.storage.store import Store


def test_persistence_transitions_and_cancellation_are_durable(repo: Path) -> None:
    task = Task(
        project=repo,
        spec=TaskSpec(description="fix", acceptance=["passes"]),
        config=load_config(repo),
    )
    first = Store(repo)
    first.create(task)
    first.transition(task, State.CLASSIFYING)
    second = Store(repo)
    assert second.load(task.id).state == State.CLASSIFYING
    second.cancel(task.id)
    first.checkpoint(task)  # stale object cannot clear cancellation
    assert first.load(task.id).cancel_requested
    assert [event["kind"] for event in first.events(task.id)] == [
        "created",
        "transition",
        "cancel_requested",
        "checkpoint",
    ]
    with pytest.raises(ValueError, match="Illegal"):
        first.transition(task, State.COMPLETED)
    assert second.load(task.id).state == State.CLASSIFYING
    first.close()
    second.close()


def test_future_schema_is_rejected(repo: Path) -> None:
    store = Store(repo)
    store.connection.execute("PRAGMA user_version=999")
    store.close()
    with pytest.raises(ValueError, match="newer"):
        Store(repo)

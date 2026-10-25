import sqlite3
from pathlib import Path

from eng.core.models import Role, Task, TaskSpec, identity
from eng.projects.config import load_config
from eng.storage.store import MIGRATIONS, Store


def test_v1_invocation_migration_preserves_row_and_permits_multiple_calls(repo: Path) -> None:
    root = repo / ".engineering/state"
    root.mkdir()
    connection = sqlite3.connect(root / "eng.sqlite3")
    connection.executescript(MIGRATIONS[0])
    task = Task(
        project=repo,
        spec=TaskSpec(description="Fix answer", acceptance=["passes"]),
        config=load_config(repo),
        execution_id="legacy-execution",
    )
    connection.execute("INSERT INTO projects VALUES (?,?)", (str(repo), "fixture"))
    connection.execute(
        "INSERT INTO tasks VALUES (?,?,?,?,0)",
        (task.id, str(repo), task.state.value, task.model_dump_json()),
    )
    connection.execute(
        "INSERT INTO executions(id,task_id,started_at) VALUES (?,?,?)",
        (task.execution_id, task.id, task.created_at),
    )
    connection.execute(
        "INSERT INTO invocations VALUES (?,?,?)",
        (task.execution_id, "codex", '{"status":"success","summary":"legacy"}'),
    )
    connection.execute("PRAGMA user_version=1")
    connection.commit()
    connection.close()
    store = Store(repo)
    assert store.connection.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    migrated = store.connection.execute("SELECT * FROM invocations").fetchone()
    assert migrated["invocation_id"] == task.execution_id
    assert migrated["role"] == "engineer" and migrated["status"] == "success"
    store.invocation(task, '{"status":"success"}', invocation_id=identity(), role=Role.REVIEWER)
    store.invocation(task, '{"status":"success"}')
    assert store.connection.execute("SELECT COUNT(*) FROM invocations").fetchone()[0] == 3
    store.close()


def test_pending_invocation_and_retry_state_are_atomic(repo: Path) -> None:
    store = Store(repo)
    task = Task(
        project=repo,
        spec=TaskSpec(description="Fix answer", acceptance=["passes"]),
        config=load_config(repo),
        execution_id=identity(),
    )
    store.create(task)
    store.start_execution(task)
    task.provider_calls = 1
    task.pending_role = Role.REVIEWER
    task.pending_invocation_id = identity()
    task.checkpoint = "provider_started"
    store.begin_invocation(task)
    other = Store(repo)
    persisted = other.load(task.id)
    assert persisted.provider_calls == 1 and persisted.pending_role == Role.REVIEWER
    assert other.connection.execute("SELECT status FROM invocations").fetchone()[0] == "started"
    invocation_id = task.pending_invocation_id
    task.pending_role = None
    task.pending_invocation_id = None
    task.checkpoint = "reviewed"
    store.complete_invocation(task, '{"status":"success"}', invocation_id, Role.REVIEWER)
    assert other.load(task.id).checkpoint == "reviewed"
    assert other.connection.execute("SELECT status FROM invocations").fetchone()[0] == "success"
    other.close()
    store.close()

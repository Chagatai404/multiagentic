import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from eng.core.models import Task, TaskSpec
from eng.core.triggers import CONTENT_DEDUP_SECONDS, TriggerOrigin, TriggerRecord
from eng.projects.config import load_config
from eng.storage.store import MIGRATIONS, Store

OLD = "2026-10-26T00:00:00+00:00"


def record(key: str, *, content_keyed: bool = False, created_at: str = OLD) -> TriggerRecord:
    return TriggerRecord(
        key=key,
        origin=TriggerOrigin.CLI,
        session_id="session",
        prompt_digest="digest",
        content_keyed=content_keyed,
        created_at=created_at,
        updated_at=created_at,
    )


def later(seconds: float) -> str:
    return (datetime.fromisoformat(OLD) + timedelta(seconds=seconds)).isoformat()


def test_first_claim_is_new_and_second_returns_existing(repo: Path) -> None:
    store = Store(repo)
    assert store.claim_trigger(record("k1"), {"prompt": "fix"}, now=OLD) is None
    duplicate = store.claim_trigger(record("k1"), {"prompt": "fix"}, now=later(1))
    assert duplicate is not None and duplicate.key == "k1"
    assert duplicate.created_at == OLD
    store.close()


def test_content_keyed_row_older_than_window_is_replaced(repo: Path) -> None:
    store = Store(repo)
    assert store.claim_trigger(record("c1", content_keyed=True), {}, now=OLD) is None
    within = later(CONTENT_DEDUP_SECONDS - 1)
    assert (
        store.claim_trigger(record("c1", content_keyed=True, created_at=within), {}, now=within)
        is not None
    )
    after = later(CONTENT_DEDUP_SECONDS + 60)
    fresh = record("c1", content_keyed=True, created_at=after)
    assert store.claim_trigger(fresh, {}, now=after) is None
    assert store.trigger("c1") is not None and store.trigger("c1").created_at == after
    store.close()


def test_id_keyed_row_is_never_replaced(repo: Path) -> None:
    store = Store(repo)
    assert store.claim_trigger(record("t1"), {}, now=OLD) is None
    much_later = later(CONTENT_DEDUP_SECONDS * 100)
    duplicate = store.claim_trigger(record("t1", created_at=much_later), {}, now=much_later)
    assert duplicate is not None and duplicate.created_at == OLD
    store.close()


def test_update_trigger_persists_status_task_and_message(repo: Path) -> None:
    store = Store(repo)
    store.claim_trigger(record("u1"), {}, now=OLD)
    store.update_trigger("u1", status="started", task_id="task-123", now=later(2))
    store.update_trigger("u1", status="failed", message="spawn failed", now=later(3))
    stored = store.trigger("u1")
    assert stored is not None
    assert stored.status == "failed"
    assert stored.task_id == "task-123"
    assert stored.message == "spawn failed"
    assert stored.updated_at == later(3)
    assert [item.key for item in store.triggers()] == ["u1"]
    assert store.trigger("missing") is None
    store.close()


def test_payload_secrets_are_redacted_in_storage(repo: Path) -> None:
    store = Store(repo)
    secret_prompt = "Fix parser API_KEY=sk-test-123456 now"
    store.claim_trigger(record("s1"), {"prompt": secret_prompt}, now=OLD)
    stored = store.connection.execute("SELECT payload FROM triggers").fetchone()[0]
    assert "sk-test-123456" not in stored
    assert "[REDACTED]" in stored
    store.close()


def test_migration_from_version_two_preserves_tasks(repo: Path) -> None:
    root = repo / ".engineering/state"
    root.mkdir()
    task = Task(
        project=repo,
        spec=TaskSpec(description="Fix answer", acceptance=["passes"]),
        config=load_config(repo),
    )
    connection = sqlite3.connect(root / "eng.sqlite3")
    connection.executescript(MIGRATIONS[0])
    connection.executescript(MIGRATIONS[1])
    connection.execute("INSERT INTO projects VALUES (?,?)", (str(repo), "fixture"))
    connection.execute(
        "INSERT INTO tasks VALUES (?,?,?,?,0)",
        (task.id, str(repo), task.state.value, task.model_dump_json()),
    )
    connection.execute("PRAGMA user_version=2")
    connection.commit()
    connection.close()
    store = Store(repo)
    assert store.connection.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    assert store.load(task.id).id == task.id
    assert store.claim_trigger(record("m1"), {}, now=OLD) is None
    store.close()


def test_concurrent_connections_claim_one_key_exactly_once(repo: Path) -> None:
    Store(repo).close()
    barrier = threading.Barrier(2)
    results: list[TriggerRecord | None] = []
    lock = threading.Lock()

    def claim(index: int) -> None:
        store = Store(repo)
        barrier.wait()
        result = store.claim_trigger(record("race-shared"), {"n": index}, now=OLD)
        store.close()
        with lock:
            results.append(result)

    threads = [threading.Thread(target=claim, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(result is None for result in results) == [False, True]
    checker = sqlite3.connect(repo / ".engineering/state/eng.sqlite3")
    assert checker.execute("SELECT COUNT(*) FROM triggers").fetchone()[0] == 1
    checker.close()

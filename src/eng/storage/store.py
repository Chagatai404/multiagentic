import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from eng.core.models import InvocationRecord, ProviderResult, Role, State, Task, identity, now
from eng.core.policy import TERMINAL, validate_transition
from eng.core.triggers import CONTENT_DEDUP_SECONDS, TriggerOrigin, TriggerRecord
from eng.execution.process import redact, redact_data

MIGRATIONS = [
    """
    CREATE TABLE projects (path TEXT PRIMARY KEY, name TEXT NOT NULL);
    CREATE TABLE tasks (id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(path),
                        state TEXT NOT NULL, payload TEXT NOT NULL,
                        cancel_requested INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE executions (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                             started_at TEXT NOT NULL, finished_at TEXT, outcome TEXT);
    CREATE TABLE events (sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                         task_id TEXT NOT NULL REFERENCES tasks(id), execution_id TEXT,
                         at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE invocations (execution_id TEXT PRIMARY KEY REFERENCES executions(id),
                              provider TEXT NOT NULL, result TEXT NOT NULL);
    CREATE TABLE verification_runs (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    task_id TEXT NOT NULL REFERENCES tasks(id), execution_id TEXT,
                                    payload TEXT NOT NULL);
    CREATE TABLE checkpoints (id INTEGER PRIMARY KEY AUTOINCREMENT,
                              task_id TEXT NOT NULL REFERENCES tasks(id), execution_id TEXT,
                              name TEXT NOT NULL, at TEXT NOT NULL);
    CREATE TABLE artifacts (id INTEGER PRIMARY KEY AUTOINCREMENT,
                           task_id TEXT NOT NULL REFERENCES tasks(id), execution_id TEXT,
                           path TEXT NOT NULL, kind TEXT NOT NULL);
    CREATE INDEX events_task ON events(task_id, sequence);
    """,
    """
    ALTER TABLE invocations RENAME TO invocations_v1;
    CREATE TABLE invocations (invocation_id TEXT PRIMARY KEY,
                              execution_id TEXT NOT NULL REFERENCES executions(id),
                              role TEXT NOT NULL, provider TEXT NOT NULL,
                              status TEXT NOT NULL, result TEXT NOT NULL);
    INSERT INTO invocations(invocation_id,execution_id,role,provider,status,result)
      SELECT execution_id,execution_id,'engineer',provider,
             COALESCE(json_extract(result,'$.status'),'unknown'),result FROM invocations_v1;
    DROP TABLE invocations_v1;
    CREATE INDEX invocations_execution ON invocations(execution_id);
    """,
    """
    CREATE TABLE triggers (key TEXT PRIMARY KEY, origin TEXT NOT NULL, session_id TEXT,
                           prompt_digest TEXT NOT NULL, content_keyed INTEGER NOT NULL,
                           task_id TEXT, status TEXT NOT NULL, message TEXT NOT NULL,
                           created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                           payload TEXT NOT NULL);
    """,
    """
    ALTER TABLE invocations ADD COLUMN model TEXT;
    """,
]


def _trigger_record(row: sqlite3.Row) -> TriggerRecord:
    return TriggerRecord(
        key=row["key"],
        origin=TriggerOrigin(row["origin"]),
        session_id=row["session_id"],
        prompt_digest=row["prompt_digest"],
        content_keyed=bool(row["content_keyed"]),
        task_id=row["task_id"],
        status=row["status"],
        message=row["message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _invocation_result(row: sqlite3.Row) -> ProviderResult | None:
    payload = json.loads(row["result"])
    if not payload or row["status"] == "started":
        return None
    # A legacy result may lack a status while retaining reported counters. The
    # row's unknown status stays visible; parsing its usage never invents success.
    if row["status"] == "unknown":
        payload["status"] = "error"
    return ProviderResult.model_validate(payload)


class Store:
    def __init__(self, project: Path) -> None:
        self.root = project / ".engineering" / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.root / "eng.sqlite3", timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version > len(MIGRATIONS):
            raise ValueError("State database was created by a newer eng version")
        for index in range(version, len(MIGRATIONS)):
            self.connection.executescript(
                "BEGIN IMMEDIATE;\n"
                + MIGRATIONS[index]
                + f"\nPRAGMA user_version={index + 1};\nCOMMIT;"
            )

    def close(self) -> None:
        self.connection.close()

    def create(self, task: Task) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO projects VALUES (?, ?)",
                (str(task.project), task.config.name),
            )
            self.connection.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, 0)",
                (task.id, str(task.project), task.state.value, task.model_dump_json()),
            )
            self._event(task, "created", {"state": task.state.value})

    def load(self, task_id: str) -> Task:
        row = self.connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise ValueError(f"Task not found: {task_id}")
        task = Task.model_validate_json(row["payload"])
        task.cancel_requested = bool(row["cancel_requested"])
        return task

    def list_tasks(self) -> list[Task]:
        return [
            self.load(row[0])
            for row in self.connection.execute("SELECT id FROM tasks ORDER BY rowid DESC")
        ]

    def save(self, task: Task) -> None:
        task.updated_at = now()
        # Never overwrite a cancellation from another process with a stale Task object.
        self.connection.execute(
            "UPDATE tasks SET state=?, payload=? WHERE id=?",
            (task.state.value, task.model_dump_json(), task.id),
        )

    def checkpoint(self, task: Task) -> None:
        with self.connection:
            self.save(task)
            self.connection.execute(
                "INSERT INTO checkpoints(task_id,execution_id,name,at) VALUES (?,?,?,?)",
                (task.id, task.execution_id, task.checkpoint, now()),
            )
            self._event(task, "checkpoint", {"name": task.checkpoint})

    def transition(self, task: Task, state: State, message: str = "") -> None:
        validate_transition(task.state, state)
        old = task.state
        task.state = state
        task.message = redact(message)
        with self.connection:
            self.save(task)
            self._event(
                task, "transition", {"from": old.value, "to": state.value, "message": task.message}
            )

    def _event(self, task: Task, kind: str, payload: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO events(task_id,execution_id,at,kind,payload) VALUES (?,?,?,?,?)",
            (task.id, task.execution_id, now(), kind, json.dumps(redact_data(payload))),
        )

    def event(self, task: Task, kind: str, payload: dict[str, Any]) -> None:
        with self.connection:
            self._event(task, kind, payload)

    def events(self, task_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM events WHERE task_id=? ORDER BY sequence", (task_id,)
            )
        ]

    def start_execution(self, task: Task) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO executions(id,task_id,started_at) VALUES (?,?,?)",
                (task.execution_id, task.id, now()),
            )
            self.save(task)

    def finish_execution(self, task: Task) -> None:
        with self.connection:
            self.save(task)
            self.connection.execute(
                "UPDATE executions SET finished_at=?,outcome=? WHERE id=?",
                (now(), task.state.value, task.execution_id),
            )

    def cancel(self, task_id: str) -> bool:
        task = self.load(task_id)
        if task.state in TERMINAL:
            return False
        with self.connection:
            self.connection.execute("UPDATE tasks SET cancel_requested=1 WHERE id=?", (task_id,))
            self._event(task, "cancel_requested", {})
        return True

    def cancelled(self, task_id: str) -> bool:
        row = self.connection.execute(
            "SELECT cancel_requested FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        return bool(row[0])

    def begin_invocation(self, task: Task) -> None:
        """Atomically reserve the side effect and save its call/retry counters."""
        if task.pending_invocation_id is None or task.pending_role is None:
            raise ValueError("Pending invocation identity and role are required")
        with self.connection:
            self.save(task)
            self.connection.execute(
                "INSERT INTO invocations VALUES (?,?,?,?,?,?,?)",
                (
                    task.pending_invocation_id,
                    task.execution_id,
                    task.pending_role.value,
                    task.spec.provider,
                    "started",
                    "{}",
                    task.pending_model,
                ),
            )
            self._event(
                task,
                "provider_started",
                {
                    "invocation_id": task.pending_invocation_id,
                    "role": task.pending_role.value,
                    "provider_calls": task.provider_calls,
                    "model": task.pending_model,
                },
            )

    def invocation(
        self,
        task: Task,
        result_json: str,
        *,
        invocation_id: str | None = None,
        role: Role = Role.ENGINEER,
    ) -> None:
        """Record a result; legacy callers may omit the per-call identity."""
        payload = redact_data(json.loads(result_json))
        with self.connection:
            self.connection.execute(
                "INSERT INTO invocations VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(invocation_id) DO UPDATE SET status=excluded.status, "
                "result=excluded.result",
                (
                    invocation_id or task.pending_invocation_id or identity(),
                    task.execution_id,
                    role.value,
                    task.spec.provider,
                    payload.get("status", "unknown"),
                    json.dumps(payload),
                    task.pending_model if invocation_id else task.spec.model,
                ),
            )

    def invocations(self, task_id: str) -> list[InvocationRecord]:
        """Authoritative call history across every execution, including crash reservations."""
        self.load(task_id)
        return [
            InvocationRecord(
                invocation_id=row["invocation_id"],
                execution_id=row["execution_id"],
                provider=row["provider"],
                model=row["model"],
                role=Role(row["role"]),
                status=row["status"],
                result=_invocation_result(row),
            )
            for row in self.connection.execute(
                "SELECT i.* FROM invocations i JOIN executions e ON i.execution_id=e.id "
                "WHERE e.task_id=? ORDER BY i.rowid",
                (task_id,),
            )
        ]

    def complete_invocation(
        self,
        task: Task,
        result_json: str,
        invocation_id: str,
        role: Role,
    ) -> None:
        """Commit successful handoff/checkpoint and result in one transaction."""
        payload = redact_data(json.loads(result_json))
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE invocations SET status=?,result=? WHERE invocation_id=?",
                (payload.get("status", "unknown"), json.dumps(payload), invocation_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Cannot finish an invocation without a durable reservation")
            self.save(task)
            self._event(
                task,
                "provider_finished",
                {
                    "invocation_id": invocation_id,
                    "role": role.value,
                    "status": payload.get("status"),
                    "checkpoint": task.checkpoint,
                },
            )

    def verification(self, task: Task) -> None:
        with self.connection:
            for result in task.verification:
                self.connection.execute(
                    "INSERT INTO verification_runs(task_id,execution_id,payload) VALUES (?,?,?)",
                    (task.id, task.execution_id, result.model_dump_json()),
                )

    def artifact(self, task: Task, path: Path, kind: str) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO artifacts(task_id,execution_id,path,kind) VALUES (?,?,?,?)",
                (task.id, task.execution_id, str(path), kind),
            )

    def claim_trigger(
        self, record: TriggerRecord, payload: dict[str, Any], *, now: str
    ) -> TriggerRecord | None:
        """Claim a trigger key atomically; return the existing duplicate, or None when claimed."""
        connection = self.connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute("SELECT * FROM triggers WHERE key=?", (record.key,)).fetchone()
            if row is not None:
                existing = _trigger_record(row)
                age = datetime.fromisoformat(now) - datetime.fromisoformat(existing.created_at)
                stale = existing.content_keyed and age > timedelta(seconds=CONTENT_DEDUP_SECONDS)
                if not stale:
                    connection.execute("COMMIT")
                    return existing
                connection.execute("DELETE FROM triggers WHERE key=?", (record.key,))
            connection.execute(
                "INSERT INTO triggers(key,origin,session_id,prompt_digest,content_keyed,task_id,"
                "status,message,created_at,updated_at,payload) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record.key,
                    record.origin.value,
                    record.session_id,
                    record.prompt_digest,
                    int(record.content_keyed),
                    record.task_id,
                    record.status,
                    redact(record.message),
                    record.created_at,
                    record.updated_at,
                    json.dumps(redact_data(payload)),
                ),
            )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        return None

    def update_trigger(
        self,
        key: str,
        *,
        status: Literal["claimed", "started", "failed"],
        task_id: str | None = None,
        message: str = "",
        now: str,
    ) -> None:
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE triggers SET status=?, task_id=COALESCE(?, task_id), message=?, "
                "updated_at=? WHERE key=?",
                (status, task_id, redact(message), now, key),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"Trigger not found: {key}")

    def trigger(self, key: str) -> TriggerRecord | None:
        row = self.connection.execute("SELECT * FROM triggers WHERE key=?", (key,)).fetchone()
        return None if row is None else _trigger_record(row)

    def triggers(self, limit: int = 50) -> list[TriggerRecord]:
        return [
            _trigger_record(row)
            for row in self.connection.execute(
                "SELECT * FROM triggers ORDER BY rowid DESC LIMIT ?", (limit,)
            )
        ]

    def export_events(self, task: Task, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "events.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in self.events(task.id)), encoding="utf-8"
        )

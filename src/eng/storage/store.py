import json
import sqlite3
from pathlib import Path
from typing import Any

from eng.core.models import State, Task, now
from eng.core.policy import TERMINAL, validate_transition
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
]


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

    def invocation(self, task: Task, result_json: str) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO invocations VALUES (?,?,?)",
                (
                    task.execution_id,
                    task.spec.provider,
                    json.dumps(redact_data(json.loads(result_json))),
                ),
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

    def export_events(self, task: Task, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "events.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in self.events(task.id)), encoding="utf-8"
        )

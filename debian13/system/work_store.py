"""Persistent, operator-review-only Work task ledger for Debian 13.

Task creation DOES NOT start AI workers, execute shell commands, submit purchases,
or issue GitHub requests. SQLite is stored in the mounted private workspace.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

MAX_TASKS = 2000
MAX_EVENTS = 5000
PAGE_SIZE = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WorkStore:
    def __init__(self, workspace: Path):
        self.db_path = workspace / ".debian13-work.sqlite3"
        with self._open() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('queued','cancelled')),
                    execution TEXT NOT NULL DEFAULT 'not_started',
                    requires_approval INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    type TEXT NOT NULL,
                    at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS tasks_latest ON tasks(created_at DESC);
                CREATE TABLE IF NOT EXISTS alex_submissions (
                    task_id TEXT PRIMARY KEY REFERENCES tasks(id),
                    remote_task_id TEXT NOT NULL,
                    submitted_at TEXT NOT NULL
                );
            """)
        os.chmod(self.db_path, 0o600)

    @contextmanager
    def _open(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=10000")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def list_tasks(self) -> list[dict]:
        with self._open() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (PAGE_SIZE,),
            )]

    def list_events(self) -> list[dict]:
        with self._open() as db:
            return [dict(row) for row in db.execute(
                "SELECT task_id,agent,type,at FROM events ORDER BY id DESC LIMIT ?",
                (PAGE_SIZE,),
            )]

    def get_task(self, task_id: str) -> dict | None:
        with self._open() as db:
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return dict(row) if row else None

    def create_task(self, kind: str, agent: str, title: str, description: str) -> dict:
        ident = str(uuid.uuid4())
        created = _now()
        with self._open() as db:
            # Lock before checking the quota so concurrent requests cannot exceed it.
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            if count >= MAX_TASKS:
                raise ValueError("Task quota reached; archive with operator review.")
            db.execute(
                "INSERT INTO tasks(id,kind,agent,title,description,status,execution,"
                "requires_approval,created_at,updated_at) "
                "VALUES (?,?,?,?,?,'queued','not_started',1,?,?)",
                (ident, kind, agent, title, description, created, created),
            )
            db.execute(
                "INSERT INTO events(task_id,agent,type,at) VALUES (?,?,?,?)",
                (ident, agent, "task_queued", created),
            )
            db.execute(
                "DELETE FROM events WHERE id NOT IN "
                "(SELECT id FROM events ORDER BY id DESC LIMIT ?)",
                (MAX_EVENTS,),
            )
        return self.get_task(ident)

    def cancel_task(self, task_id: str) -> dict | None:
        with self._open() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT agent,status FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                return None
            if row["status"] == "queued":
                stamp = _now()
                db.execute(
                    "UPDATE tasks SET status='cancelled',updated_at=? WHERE id=? AND status='queued'",
                    (stamp, task_id),
                )
                db.execute(
                    "INSERT INTO events(task_id,agent,type,at) VALUES (?,?,?,?)",
                    (task_id, row["agent"], "task_cancelled", stamp),
                )
        return self.get_task(task_id)

    def get_alex_submission(self, task_id: str) -> dict | None:
        with self._open() as db:
            row = db.execute(
                "SELECT remote_task_id, submitted_at FROM alex_submissions WHERE task_id=?",
                (task_id,),
            ).fetchone()
        return {
            "status": "accepted_by_remote_api",
            "remoteTaskId": row["remote_task_id"],
            "submittedAt": row["submitted_at"],
            "agentExecutionVerified": False,
            "pullRequestVerified": False,
        } if row else None

    def record_alex_submission(self, task_id: str, remote_task_id: str) -> dict:
        with self._open() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status,agent FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
            if row is None or row["status"] != "queued" or row["agent"] != "alex":
                raise ValueError("Task no longer eligible for Alex dispatch.")
            stamp = _now()
            db.execute(
                "INSERT OR IGNORE INTO alex_submissions(task_id,remote_task_id,submitted_at) "
                "VALUES (?,?,?)", (task_id, remote_task_id, stamp)
            )
            db.execute(
                "INSERT INTO events(task_id,agent,type,at) "
                "SELECT ?,?,?,? WHERE changes() > 0",
                (task_id, "alex", "task_accepted_by_remote_api", stamp)
            )
        return self.get_alex_submission(task_id)

"""Durable, review-only task ledger for the independent Debian 13 prototype.

This module records plans and audit events; it does NOT execute code, issue
GitHub requests, start background workers, or grant privileges.
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

TASK_LIMIT = 2000
EVENT_LIMIT = 5000
VISIBLE_LIMIT = 100

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def as_dict(record: sqlite3.Row) -> dict:
    return dict(record)

class WorkStore:
    def __init__(self, workspace: Path):
        self.path = workspace / ".debian13-work.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript("""
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
                CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_id ON events(id DESC);
            """)
        # The workspace belongs to a dedicated non-root service account.
        os.chmod(self.path, 0o600)

    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def list_tasks(self) -> list[dict]:
        with self._connection() as db:
            return [as_dict(row) for row in db.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (VISIBLE_LIMIT,),
            )]

    def list_events(self) -> list[dict]:
        with self._connection() as db:
            return [as_dict(row) for row in db.execute(
                "SELECT task_id,agent,type,at FROM events ORDER BY id DESC LIMIT ?",
                (VISIBLE_LIMIT,),
            )]

    def get_task(self, task_id: str) -> dict | None:
        with self._connection() as db:
            result = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return as_dict(result) if result else None

    def create_task(self, kind: str, agent: str, title: str, description: str) -> dict:
        task_id = str(uuid.uuid4())
        stamp = now()
        with self._connection() as db:
            count = db.execute("SELECT count(*) FROM tasks").fetchone()[0]
            if count >= TASK_LIMIT:
                raise ValueError("Task limit reached; archive explicitly before creating more.")
            db.execute(
                "INSERT INTO tasks(id,kind,agent,title,description,status,execution,"
                "requires_approval,created_at,updated_at) VALUES (?,?,?,?,?,'queued','not_started',1,?,?)",
                (task_id, kind, agent, title, description, stamp, stamp),
            )
            db.execute(
                "INSERT INTO events(task_id,agent,type,at) VALUES (?,?,?,?)",
                (task_id, agent, "task_queued", stamp),
            )
            db.execute(
                "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)",
                (EVENT_LIMIT,),
            )
        return self.get_task(task_id)

    def cancel_task(self, task_id: str) -> dict | None:
        with self._connection() as db:
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                return None
            if row["status"] == "queued":
                stamp = now()
                db.execute(
                    "UPDATE tasks SET status='cancelled',updated_at=? WHERE id=? AND status='queued'",
                    (stamp, task_id),
                )
                db.execute(
                    "INSERT INTO events(task_id,agent,type,at) VALUES (?,?,?,?)",
                    (task_id, row["agent"], "task_cancelled", stamp),
                )
        return self.get_task(task_id)

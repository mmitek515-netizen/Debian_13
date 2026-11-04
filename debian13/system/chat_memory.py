"""Private SQLite history and explicitly saved operator notes for Dialog Triady.

This is application-local memory, not ChatGPT account memory. No image bytes,
API tokens or credentials are stored. All content is operator-controlled.
"""
from __future__ import annotations

import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

MAX_CONTEXT_MESSAGES = 24
MAX_HISTORY_MESSAGES = 300
MAX_NOTES = 40
MAX_NOTE_LENGTH = 600


class ChatMemory:
    def __init__(self, workspace: Path):
        self.path = Path(workspace) / "dialog_triady.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, title TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                agent TEXT NOT NULL, role TEXT NOT NULL,
                content TEXT NOT NULL, source TEXT NOT NULL, created_at REAL NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id)")
            db.execute("""CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL UNIQUE, created_at REAL NOT NULL)""")
        os.chmod(self.path, 0o600)

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 10000")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def exists(self, session_id: str) -> bool:
        with self._connection() as db:
            return db.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone() is not None

    def context(self, session_id: str | None) -> list[dict[str, str]]:
        if not session_id:
            return []
        with self._connection() as db:
            rows = db.execute("""SELECT role, agent, content FROM messages
                WHERE session_id=? ORDER BY id DESC LIMIT ?""",
                (session_id, MAX_CONTEXT_MESSAGES)).fetchall()
        return [{"role": row["role"],
                 "content": (f"[{row['agent']}] " if row["role"] == "assistant" else "") + row["content"]}
                for row in reversed(rows)]

    def save_exchange(self, session_id: str | None, agent: str, message: str,
                      response: str, source: str, image_attached: bool = False) -> str:
        session_id = session_id or str(uuid.uuid4())
        now = time.time()
        with self._connection() as db:
            db.execute("""INSERT OR IGNORE INTO sessions(id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)""", (session_id, message[:64], now, now))
            user_text = message + (" [dołączono obraz; plik nie jest zapisywany]" if image_attached else "")
            db.execute("""INSERT INTO messages(session_id, agent, role, content, source, created_at)
                VALUES (?, ?, 'user', ?, 'operator', ?)""", (session_id, agent, user_text, now))
            db.execute("""INSERT INTO messages(session_id, agent, role, content, source, created_at)
                VALUES (?, ?, 'assistant', ?, ?, ?)""", (session_id, agent, response, source, now))
            db.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
            db.execute("""DELETE FROM messages WHERE session_id=? AND id NOT IN
                (SELECT id FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?)""",
                (session_id, session_id, MAX_HISTORY_MESSAGES))
        return session_id

    def get_messages(self, session_id: str) -> list[dict] | None:
        with self._connection() as db:
            if db.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone() is None:
                return None
            rows = db.execute("""SELECT agent, role, content, source, created_at
                FROM messages WHERE session_id=? ORDER BY id""", (session_id,)).fetchall()
            return [dict(row) for row in rows]

    def sessions(self) -> list[dict]:
        with self._connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT id, title, updated_at FROM sessions ORDER BY updated_at DESC LIMIT 50")]

    def notes(self) -> list[dict]:
        with self._connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT id, content, created_at FROM memories ORDER BY id DESC LIMIT ?", (MAX_NOTES,))]

    def add_note(self, content: str) -> dict:
        content = content.strip()
        if not content or len(content) > MAX_NOTE_LENGTH:
            raise ValueError("A saved memory must have 1-600 characters.")
        with self._connection() as db:
            if db.execute("SELECT COUNT(*) FROM memories").fetchone()[0] >= MAX_NOTES:
                raise ValueError("Memory is full; delete a note to add another.")
            try:
                cur = db.execute("INSERT INTO memories(content, created_at) VALUES (?, ?)",
                                 (content, time.time()))
            except sqlite3.IntegrityError as exc:
                raise ValueError("This note already exists.") from exc
            return {"id": cur.lastrowid, "content": content}

    def delete_note(self, note_id: int) -> bool:
        with self._connection() as db:
            return db.execute("DELETE FROM memories WHERE id=?", (note_id,)).rowcount > 0

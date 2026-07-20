from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    compacted_through_id INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    tool_call_id TEXT,
                    tool_calls_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS todos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    due_date TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    step INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    duration_ms INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, id);
                CREATE INDEX IF NOT EXISTS idx_traces_session
                    ON traces(session_id, id);
                CREATE INDEX IF NOT EXISTS idx_todos_session
                    ON todos(session_id, id);
                """
            )
            db.execute(
                """
                UPDATE sessions
                SET title = substr(trim((
                    SELECT content
                    FROM messages
                    WHERE messages.session_id = sessions.id
                      AND role = 'user'
                      AND trim(COALESCE(content, '')) <> ''
                    ORDER BY id
                    LIMIT 1
                )), 1, 2)
                WHERE EXISTS (
                    SELECT 1
                    FROM messages
                    WHERE messages.session_id = sessions.id
                      AND role = 'user'
                      AND trim(COALESCE(content, '')) <> ''
                )
                """
            )

    def create_session(self, user_id: str, title: str) -> dict[str, Any]:
        session_id = f"ses_{uuid.uuid4().hex[:16]}"
        now = utc_now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO sessions(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                (session_id, user_id, title, now, now),
            )
        return self.get_session(session_id)

    def list_sessions(self, user_id: str = "demo-user") -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM sessions WHERE user_id=? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown session: {session_id}")
        return dict(row)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its messages, todos and traces via FK cascades."""
        with self._connect() as db:
            cursor = db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            return cursor.rowcount > 0

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str | None,
        *,
        tool_call_id: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> int:
        now = utc_now()
        with self._connect() as db:
            is_first_user_message = role == "user" and db.execute(
                "SELECT 1 FROM messages WHERE session_id=? AND role='user' LIMIT 1",
                (session_id,),
            ).fetchone() is None
            cursor = db.execute(
                """
                INSERT INTO messages(
                    session_id,role,content,tool_call_id,tool_calls_json,created_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    session_id,
                    role,
                    content,
                    tool_call_id,
                    json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                    now,
                ),
            )
            db.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id)
            )
            if is_first_user_message and content and content.strip():
                db.execute(
                    "UPDATE sessions SET title=? WHERE id=?",
                    (content.strip()[:2], session_id),
                )
            return int(cursor.lastrowid)

    def list_messages(
        self, session_id: str, *, limit: int | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM messages WHERE session_id=? ORDER BY id DESC"
        params: tuple[Any, ...] = (session_id,)
        if limit is not None:
            query += " LIMIT ?"
            params = (session_id, limit)
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        values = [dict(row) for row in reversed(rows)]
        for value in values:
            raw = value.pop("tool_calls_json")
            value["tool_calls"] = json.loads(raw) if raw else []
        return values

    def message_count(self, session_id: str) -> int:
        with self._connect() as db:
            return int(
                db.execute(
                    "SELECT COUNT(*) FROM messages WHERE session_id=?", (session_id,)
                ).fetchone()[0]
            )

    def uncompacted_messages(
        self, session_id: str, *, before_last: int
    ) -> list[dict[str, Any]]:
        session = self.get_session(session_id)
        with self._connect() as db:
            cutoff = db.execute(
                """
                SELECT id FROM messages WHERE session_id=?
                ORDER BY id DESC LIMIT 1 OFFSET ?
                """,
                (session_id, before_last),
            ).fetchone()
            if cutoff is None:
                return []
            rows = db.execute(
                """
                SELECT * FROM messages
                WHERE session_id=? AND id>? AND id<=?
                ORDER BY id
                """,
                (session_id, session["compacted_through_id"], cutoff["id"]),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_summary(self, session_id: str, summary: str, through_id: int) -> None:
        with self._connect() as db:
            db.execute(
                """
                UPDATE sessions
                SET summary=?, compacted_through_id=?, updated_at=?
                WHERE id=?
                """,
                (summary, through_id, utc_now(), session_id),
            )

    def add_trace(
        self,
        session_id: str,
        run_id: str,
        step: int,
        event_type: str,
        payload: dict[str, Any],
        duration_ms: int | None = None,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO traces(
                    session_id,run_id,step,event_type,payload_json,duration_ms,created_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    session_id,
                    run_id,
                    step,
                    event_type,
                    json.dumps(payload, ensure_ascii=False),
                    duration_ms,
                    utc_now(),
                ),
            )

    def list_traces(
        self, session_id: str, *, run_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._connect() as db:
            if run_id:
                rows = db.execute(
                    """
                    SELECT * FROM traces WHERE session_id=? AND run_id=?
                    ORDER BY id LIMIT ?
                    """,
                    (session_id, run_id, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT * FROM traces WHERE session_id=?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (session_id, limit),
                ).fetchall()
                rows = list(reversed(rows))
        values = [dict(row) for row in rows]
        for value in values:
            value["payload"] = json.loads(value.pop("payload_json"))
        return values

    def create_todo(
        self, session_id: str, title: str, due_date: str | None
    ) -> dict[str, Any]:
        with self._connect() as db:
            cursor = db.execute(
                """
                INSERT INTO todos(session_id,title,status,due_date,created_at)
                VALUES(?,?,'pending',?,?)
                """,
                (session_id, title, due_date, utc_now()),
            )
            todo_id = int(cursor.lastrowid)
            row = db.execute("SELECT * FROM todos WHERE id=?", (todo_id,)).fetchone()
        return dict(row)

    def list_todos(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM todos WHERE session_id=? ORDER BY id DESC",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def complete_todo(self, session_id: str, item_id: int) -> dict[str, Any] | None:
        with self._connect() as db:
            cursor = db.execute(
                """
                UPDATE todos SET status='completed'
                WHERE id=? AND session_id=?
                """,
                (item_id, session_id),
            )
            if cursor.rowcount == 0:
                return None
            row = db.execute("SELECT * FROM todos WHERE id=?", (item_id,)).fetchone()
        return dict(row)

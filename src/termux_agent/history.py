"""Histórico persistente local em SQLite; cada sessão mantém contexto próprio."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
import time


class HistoryStore:
    def __init__(self, database_path: str, limit: int = 20):
        self.path = database_path if database_path == ":memory:" else str(Path(database_path).expanduser())
        self.limit = limit
        self._lock = threading.RLock()
        if database_path != ":memory:":
            Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id)")
        if database_path != ":memory:":
            try:
                Path(self.path).chmod(0o600)
            except OSError:
                pass

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, session_id: str) -> list[dict[str, str]]:
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, self.limit),
            ).fetchall()
        rows.reverse()
        return [{"role": role, "content": content} for role, content in rows]

    def add_exchange(self, session_id: str, user_message: str, assistant_message: str) -> None:
        now = int(time.time())
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.executemany(
                "INSERT INTO messages(session_id, role, content, created_at) VALUES(?,?,?,?)",
                [(session_id, "user", user_message, now),
                 (session_id, "assistant", assistant_message, now)],
            )
            db.execute(
                "DELETE FROM messages WHERE session_id=? AND id NOT IN "
                "(SELECT id FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?)",
                (session_id, session_id, self.limit),
            )

    def delete(self, session_id: str) -> int:
        with self._lock, self._connect() as db:
            cursor = db.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            return cursor.rowcount

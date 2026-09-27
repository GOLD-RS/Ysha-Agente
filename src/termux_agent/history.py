"""Histórico persistente local em SQLite; cada sessão mantém contexto próprio."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid
import zlib


DEFAULT_ARCHIVE_TRIGGER = 500
DEFAULT_ARCHIVE_KEEP = 400
DEFAULT_ARCHIVE_BATCH = 100


class HistoryStore:
    def __init__(
        self,
        database_path: str,
        limit: int = 20,
        archive_trigger: int = DEFAULT_ARCHIVE_TRIGGER,
        archive_keep: int = DEFAULT_ARCHIVE_KEEP,
        archive_batch: int = DEFAULT_ARCHIVE_BATCH,
    ):
        self._memory_anchor = None
        self._uri = database_path == ":memory:"
        if self._uri:
            self.path = f"file:ysha-{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._memory_anchor = sqlite3.connect(self.path, uri=True)
        else:
            self.path = str(Path(database_path).expanduser())
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.limit = max(2, int(limit))
        self.limit -= self.limit % 2
        self.archive_trigger = max(self.limit, int(archive_trigger))
        self.archive_trigger += self.archive_trigger % 2
        self.archive_keep = max(self.limit, min(self.archive_trigger, int(archive_keep)))
        self.archive_keep -= self.archive_keep % 2
        self.archive_batch = max(2, int(archive_batch))
        self.archive_batch -= self.archive_batch % 2
        self._lock = threading.RLock()
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
            db.execute("""CREATE TABLE IF NOT EXISTS message_archives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                first_message_id INTEGER NOT NULL,
                last_message_id INTEGER NOT NULL,
                message_count INTEGER NOT NULL,
                compressed_payload BLOB NOT NULL,
                created_at INTEGER NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_archives_session ON message_archives(session_id, first_message_id)")
        if database_path != ":memory:":
            try:
                Path(self.path).chmod(0o600)
            except OSError:
                pass

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10, uri=self._uri)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, session_id: str) -> list[dict[str, str]]:
        """Return the complete transcript, including compressed archive chunks."""
        with self._lock, self._connect() as db:
            archives = db.execute(
                "SELECT compressed_payload, message_count FROM message_archives WHERE session_id=? ORDER BY first_message_id",
                (session_id,),
            ).fetchall()
            rows = db.execute(
                "SELECT role, content FROM messages WHERE session_id=? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        messages = []
        try:
            for payload, expected_count in archives:
                chunk = json.loads(zlib.decompress(payload).decode("utf-8"))
                if (
                    not isinstance(chunk, list)
                    or len(chunk) != expected_count
                    or any(
                        not isinstance(item, dict)
                        or item.get("role") not in ("user", "assistant")
                        or not isinstance(item.get("content"), str)
                        for item in chunk
                    )
                ):
                    raise ValueError
                messages.extend(
                    {"role": item["role"], "content": item["content"]}
                    for item in chunk
                )
        except (ValueError, KeyError, TypeError, zlib.error, UnicodeDecodeError):
            raise RuntimeError("O arquivo de histórico contém um bloco compactado inválido.") from None
        messages.extend({"role": role, "content": content} for role, content in rows)
        return messages

    def get_recent(self, session_id: str, limit: int | None = None) -> list[dict[str, str]]:
        """Return a bounded tail for prompts or lightweight UI restoration."""
        limit = self.limit if limit is None else max(0, limit)
        if limit == 0:
            return []
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
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
            count = db.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            if count > self.archive_trigger:
                archive_count = min(count - self.archive_keep, self.archive_batch)
                rows = db.execute(
                    "SELECT id, role, content, created_at FROM messages "
                    "WHERE session_id=? ORDER BY id ASC LIMIT ?",
                    (session_id, archive_count),
                ).fetchall()
                if rows:
                    payload = zlib.compress(json.dumps(
                        [{"id": row[0], "role": row[1], "content": row[2], "created_at": row[3]}
                         for row in rows],
                        ensure_ascii=False, separators=(",", ":"),
                    ).encode("utf-8"), level=1)
                    db.execute(
                        "INSERT INTO message_archives(session_id, first_message_id, last_message_id, "
                        "message_count, compressed_payload, created_at) VALUES(?,?,?,?,?,?)",
                        (session_id, rows[0][0], rows[-1][0], len(rows), payload, now),
                    )
                    db.execute(
                        "DELETE FROM messages WHERE session_id=? AND id<=?",
                        (session_id, rows[-1][0]),
                    )

    def delete(self, session_id: str) -> int:
        with self._lock, self._connect() as db:
            current = db.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            archived = db.execute(
                "SELECT COALESCE(SUM(message_count),0) FROM message_archives WHERE session_id=?",
                (session_id,),
            ).fetchone()[0]
            db.execute("DELETE FROM message_archives WHERE session_id=?", (session_id,))
            return current.rowcount + archived

    def close(self) -> None:
        with self._lock:
            if self._memory_anchor is not None:
                self._memory_anchor.close()
                self._memory_anchor = None

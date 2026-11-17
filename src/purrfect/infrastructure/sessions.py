"""Tenant-scoped conversation state with bounded memory and SQLite adapters."""
import json
import sqlite3
from collections import OrderedDict
from pathlib import Path
from threading import RLock


class MemorySessions:
    def __init__(self, max_sessions: int = 1024, history_limit: int = 6):
        if max_sessions < 1 or history_limit < 1:
            raise ValueError("Invalid session bounds")
        self.max_sessions = max_sessions
        self.history_limit = history_limit
        self._sessions = OrderedDict()
        self._lock = RLock()

    def read(self, tenant: str, session: str) -> tuple[tuple[str, str], ...]:
        with self._lock:
            key = (tenant, session)
            if key in self._sessions:
                self._sessions.move_to_end(key)
            return tuple(self._sessions.get(key, ()))

    def append(self, tenant: str, session: str, question: str, answer: str) -> None:
        with self._lock:
            key = (tenant, session)
            history = self._sessions.setdefault(key, [])
            history.append((question, answer))
            self._sessions[key] = history[-self.history_limit:]
            self._sessions.move_to_end(key)
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)


class SQLiteSessions:
    """Single-host persistence. Not a distributed session coordinator."""
    def __init__(self, path: str | Path, history_limit: int = 6):
        if history_limit < 1:
            raise ValueError("Invalid history limit")
        self.history_limit = history_limit
        self._lock = RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self._db.execute("PRAGMA busy_timeout=10000")
        self._db.execute("""CREATE TABLE IF NOT EXISTS conversation_turns (
            tenant_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL
        )""")
        self._db.execute("""CREATE INDEX IF NOT EXISTS idx_conversation_history
            ON conversation_turns(tenant_id, session_id, sequence)""")
        self._db.commit()

    def read(self, tenant: str, session: str) -> tuple[tuple[str, str], ...]:
        with self._lock:
            rows = self._db.execute(
                """SELECT question, answer FROM conversation_turns
                   WHERE tenant_id=? AND session_id=?
                   ORDER BY sequence DESC LIMIT ?""",
                (tenant, session, self.history_limit),
            ).fetchall()
            return tuple(reversed(rows))

    def append(self, tenant: str, session: str, question: str, answer: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO conversation_turns(tenant_id, session_id, question, answer) VALUES (?, ?, ?, ?)",
                (tenant, session, question, answer),
            )
            self._db.execute(
                """DELETE FROM conversation_turns
                   WHERE tenant_id=? AND session_id=? AND sequence NOT IN (
                     SELECT sequence FROM conversation_turns
                     WHERE tenant_id=? AND session_id=? ORDER BY sequence DESC LIMIT ?
                   )""",
                (tenant, session, tenant, session, self.history_limit),
            )

    def close(self) -> None:
        with self._lock:
            self._db.close()

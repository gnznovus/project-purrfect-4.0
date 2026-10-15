"""Custom SQLite reference implementation for the recovery comparison."""

import json
import sqlite3
from pathlib import Path

from purrfect.guidance import GuidanceDefinition
from purrfect.stateful import TaskState, Turn, advance


class CustomConversation:
    def __init__(self, definition: GuidanceDefinition, db_path: str | Path | None = None):
        self.definition = definition
        self.sessions: dict[str, TaskState] = {}
        self.db_path = str(db_path) if db_path is not None else None
        if self.db_path is not None:
            with sqlite3.connect(self.db_path) as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS sessions "
                    "(session_id TEXT PRIMARY KEY, state TEXT NOT NULL)"
                )

    def _load(self, session_id: str) -> TaskState:
        if self.db_path is None:
            return self.sessions.get(session_id, TaskState())
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT state FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return TaskState()
        data = json.loads(row[0])
        return TaskState(data["answers"], data["started"])

    def send(self, session_id: str, turn: Turn):
        if not session_id:
            raise ValueError("Session ID required")
        state = self._load(session_id)
        updated, response = advance(self.definition, state, turn)
        if self.db_path is None:
            self.sessions[session_id] = updated
        else:
            payload = json.dumps({"started": updated.started, "answers": updated.answers})
            with sqlite3.connect(self.db_path) as connection:
                connection.execute(
                    "INSERT INTO sessions (session_id, state) VALUES (?, ?) "
                    "ON CONFLICT(session_id) DO UPDATE SET state=excluded.state",
                    (session_id, payload),
                )
        return response

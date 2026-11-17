"""Durable benchmark metadata; never store prompts, responses, or credentials."""
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path


class BenchmarkStore:
    def __init__(self, path: str | Path):
        self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self._lock = threading.RLock()
        with self._lock, self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS benchmark_runs (
                id TEXT PRIMARY KEY,
                started_at INTEGER NOT NULL,
                completed_at INTEGER,
                profile TEXT NOT NULL,
                model_label TEXT NOT NULL,
                requested INTEGER NOT NULL,
                concurrency INTEGER NOT NULL,
                state TEXT NOT NULL,
                report TEXT
            )""")
            # Crash recovery: an unfinished run cannot be resumed safely.
            self._db.execute(
                "UPDATE benchmark_runs SET state='interrupted', completed_at=? "
                "WHERE state='running'", (int(time.time()),),
            )

    def start(self, *, profile: str, model_label: str, samples: int,
              concurrency: int) -> str:
        run_id = uuid.uuid4().hex
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO benchmark_runs VALUES (?, ?, NULL, ?, ?, ?, ?, 'running', NULL)",
                (run_id, int(time.time()), profile, model_label, samples, concurrency),
            )
        return run_id

    def complete(self, run_id: str, report: dict, state: str = "completed") -> None:
        if state not in ("completed", "interrupted"):
            raise ValueError("Invalid run state")
        with self._lock, self._db:
            self._db.execute(
                "UPDATE benchmark_runs SET state=?, completed_at=?, report=? WHERE id=?",
                (state, int(time.time()), json.dumps(report, separators=(",", ":")), run_id),
            )

    @staticmethod
    def _row(row):
        if row is None:
            return None
        return {
            "id": row[0], "started_at": row[1], "completed_at": row[2],
            "profile": row[3], "model_label": row[4],
            "requested": row[5], "concurrency": row[6],
            "state": row[7], "report": json.loads(row[8]) if row[8] else None,
        }

    def list(self, limit: int = 30) -> list[dict]:
        if not 1 <= limit <= 100:
            raise ValueError("Invalid history size")
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM benchmark_runs ORDER BY started_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def get(self, run_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM benchmark_runs WHERE id=?", (run_id,),
            ).fetchone()
        return self._row(row)

    def close(self):
        with self._lock:
            self._db.close()

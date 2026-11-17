"""Durable Sophia approved-knowledge catalog.

Local SQLite storage for approved revisions.
Publication remains restricted to the trusted operator CLI.
"""
import json
import sqlite3
from pathlib import Path
from threading import RLock

from purrfect.sophira import KnowledgeItem, KnowledgePackage, SophiraCatalog


def encode(package: KnowledgePackage) -> str:
    return json.dumps({
        "product_id": package.product_id, "product_version": package.product_version,
        "revision": package.revision, "contract_version": package.contract_version,
        "digest": package.digest,
        "items": [{"id": item.id, "content": item.content, "source": item.source, **({"entry_revision": item.entry_revision, "change_note": item.change_note} if item.entry_revision is not None else {})}
                  for item in package.items],
    }, sort_keys=True)


def decode(raw: str) -> KnowledgePackage:
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {
        "product_id", "product_version", "revision", "contract_version", "digest", "items"
    } or not isinstance(value["items"], list):
        raise ValueError("Invalid persisted knowledge")
    package = KnowledgePackage(value["product_id"], value["product_version"],
                               value["revision"], tuple(KnowledgeItem(**item) for item in value["items"]),
                               value["contract_version"])
    if package.digest != value["digest"]:
        raise ValueError("Persisted knowledge checksum mismatch")
    return package


class DurableSophira(SophiraCatalog):
    """SQLite is owned by Sophira; Purra only receives a client adapter."""
    def __init__(self, path: str | Path):
        super().__init__()
        self._lock = RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("""CREATE TABLE IF NOT EXISTS knowledge_revisions (
            product_id TEXT NOT NULL, product_version TEXT NOT NULL,
            revision INTEGER NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY (product_id, product_version, revision))""")
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM knowledge_revisions ORDER BY product_id, product_version, revision"
            ).fetchall()
            for (raw,) in rows:
                super().publish_approved(decode(raw), approved=True)

    def publish_approved(self, package: KnowledgePackage, *, approved: bool = False):
        if approved is not True:
            raise PermissionError("Explicit approval required")
        with self._lock:
            key = (package.product_id, package.product_version)
            previous = self.latest(*key)
            expected = previous + 1 if previous is not None else 1
            if package.revision != expected:
                raise ValueError("Non-sequential revision")
            # Validate approval, notes and monotonic entry revisions BEFORE writing.
            super().publish_approved(package, approved=True)
            try:
                with self._db:
                    self._db.execute(
                        "INSERT INTO knowledge_revisions VALUES (?, ?, ?, ?)",
                        (package.product_id, package.product_version, package.revision, encode(package)),
                    )
            except Exception:
                self._history[key].pop()
                raise

    def _refresh_from_db(self):
        # Other trusted operator processes may publish without restarting Purra.
        rows = self._db.execute(
            "SELECT payload FROM knowledge_revisions ORDER BY product_id, product_version, revision"
        ).fetchall()
        for (raw,) in rows:
            package = decode(raw)
            key = (package.product_id, package.product_version)
            history = self._history.get(key, [])
            if package.revision > (history[-1].revision if history else 0):
                super().publish_approved(package, approved=True)

    def entry_history(self, product_id, product_version, entry_id):
        with self._lock:
            self._refresh_from_db()
            return super().entry_history(product_id, product_version, entry_id)

    def latest(self, product_id, product_version):
        with self._lock:
            self._refresh_from_db()
            return super().latest(product_id, product_version)

    def lease(self, product_id, product_version, revision=None):
        with self._lock:
            self._refresh_from_db()
            return super().lease(product_id, product_version, revision)

    def close(self):
        self._db.close()

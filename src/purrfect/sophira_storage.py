"""Durable Sophira catalog and site-local lease store.

Local SQLite adapters exercise future independent deployment contracts.
No unauthenticated publication route is exposed to WordPress or the chat API.
"""
import json
import sqlite3
from pathlib import Path
from threading import RLock

from purrfect.sophira import KnowledgeItem, KnowledgePackage, KnowledgeCache, LocalSophiraClient, SophiraCatalog


def encode(package: KnowledgePackage) -> str:
    return json.dumps({
        "product_id": package.product_id, "product_version": package.product_version,
        "revision": package.revision, "contract_version": package.contract_version,
        "digest": package.digest,
        "items": [{"id": item.id, "content": item.content, "source": item.source}
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
            with self._db:
                self._db.execute(
                    "INSERT INTO knowledge_revisions VALUES (?, ?, ?, ?)",
                    (package.product_id, package.product_version, package.revision, encode(package)),
                )
            super().publish_approved(package, approved=True)

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


class SiteLeaseStore:
    """Per-site local cache; one site cannot clobber another's lease."""
    def __init__(self, path: str | Path, site_id: str):
        if not isinstance(site_id, str) or not site_id.strip():
            raise ValueError("Site identity required")
        self.site_id = site_id
        self._db = sqlite3.connect(str(path))
        self._db.execute("""CREATE TABLE IF NOT EXISTS local_leases (
            site_id TEXT NOT NULL, product_id TEXT NOT NULL,
            product_version TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(site_id, product_id, product_version))""")

    def refresh(self, client: LocalSophiraClient, product_id: str, product_version: str) -> bool:
        cache = KnowledgeCache(product_id, product_version)
        before = self.get(product_id, product_version)
        cache.current = before
        if not cache.refresh(client):
            return False
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO local_leases VALUES (?, ?, ?, ?)",
                (self.site_id, product_id, product_version, encode(cache.current)),
            )
        return True

    def get(self, product_id: str, product_version: str) -> KnowledgePackage | None:
        row = self._db.execute(
            "SELECT payload FROM local_leases WHERE site_id=? AND product_id=? AND product_version=?",
            (self.site_id, product_id, product_version),
        ).fetchone()
        return decode(row[0]) if row else None

    def close(self):
        self._db.close()

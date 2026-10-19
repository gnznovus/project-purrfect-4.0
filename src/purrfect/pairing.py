"""Durable, multi-tenant Assistant pairing. UUID is identity, never authorization."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit


def valid_uuid7(value: str) -> bool:
    try:
        return isinstance(value, str) and uuid.UUID(value).version == 7 and str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class PairingRegistry:
    """Server-side authority; possession of assistant_id alone gives no access."""

    def __init__(self, path: str | Path):
        self._lock = RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("""CREATE TABLE IF NOT EXISTS pairing_codes (
            hash TEXT PRIMARY KEY, expires INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS assistants (
            assistant_id TEXT PRIMARY KEY, site_id TEXT NOT NULL UNIQUE,
            site_url TEXT NOT NULL, credential_hash TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('active','revoked')),
            paired_at INTEGER NOT NULL
        )""")
        self.db.commit()

    def create_pairing_code(self, *, ttl_seconds: int = 600) -> str:
        if not 30 <= ttl_seconds <= 3600:
            raise ValueError("Invalid pairing code lifetime")
        code = secrets.token_urlsafe(32)
        with self._lock, self.db:
            self.db.execute("INSERT INTO pairing_codes(hash,expires) VALUES (?,?)",
                            (_digest(code), int(time.time()) + ttl_seconds))
        return code

    def pair(self, *, code: str, assistant_id: str, site_id: str, site_url: str) -> dict:
        if not valid_uuid7(assistant_id) or not valid_uuid7(site_id):
            raise ValueError("Valid UUIDv7 assistant and site identities required")
        if not isinstance(site_url, str) or len(site_url) > 2048:
            raise ValueError("An HTTPS site URL is required")
        try:
            parsed = urlsplit(site_url)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.port == 0
                or any(ch.isspace() for ch in site_url)):
                raise ValueError("Invalid HTTPS site URL")
        except ValueError:
            raise ValueError("An HTTPS site URL without credentials is required") from None
        if not isinstance(code, str) or len(code) > 160:
            raise PermissionError("Invalid pairing code")
        now = int(time.time())
        with self._lock, self.db:
            ticket = self.db.execute(
                "SELECT expires,used FROM pairing_codes WHERE hash=?", (_digest(code),)
            ).fetchone()
            if not ticket or ticket[1] or ticket[0] <= now:
                raise PermissionError("Invalid or expired pairing code")
            # Never use pairing to overwrite a registered site or to bypass revocation.
            if self.db.execute("SELECT 1 FROM assistants WHERE assistant_id=? OR site_id=?",
                               (assistant_id, site_id)).fetchone():
                raise PermissionError("Identity already registered; use an explicit recovery flow")
            secret = secrets.token_urlsafe(48)
            self.db.execute("INSERT INTO assistants VALUES (?,?,?,?,?,?)",
                            (assistant_id, site_id, site_url, _digest(secret), "active", now))
            self.db.execute("UPDATE pairing_codes SET used=1 WHERE hash=?", (_digest(code),))
            return {"assistant_id": assistant_id, "site_id": site_id,
                    "credential": secret, "status": "paired"}

    def authenticate(self, assistant_id: str, credential: str) -> dict | None:
        if not valid_uuid7(assistant_id) or not isinstance(credential, str):
            return None
        with self._lock:
            row = self.db.execute(
                "SELECT site_id,site_url,credential_hash,state FROM assistants WHERE assistant_id=?",
                (assistant_id,)
            ).fetchone()
        if not row or row[3] != "active" or not hmac.compare_digest(row[2], _digest(credential)):
            return None
        return {"assistant_id": assistant_id, "site_id": row[0], "site_url": row[1]}

    def revoke(self, assistant_id: str) -> bool:
        with self._lock, self.db:
            cursor = self.db.execute(
                "UPDATE assistants SET state='revoked' WHERE assistant_id=? AND state='active'",
                (assistant_id,))
            return cursor.rowcount == 1

    def close(self):
        self.db.close()

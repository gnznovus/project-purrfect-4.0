"""Gateway-issued, tenant-bound bearer proof for anonymous conversation sessions.

This establishes possession of a session ticket, not human identity. Only the
authenticated Assistant backend may mint tickets; external identity is future work.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass


class InvalidSession(Exception):
    """Missing, invalid, expired, or mismatched session ticket."""


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(data: str) -> bytes:
    if not data.isascii() or not data or len(data) > 1024:
        raise InvalidSession("Invalid session credential")
    return base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)


@dataclass(frozen=True)
class IssuedSession:
    session_id: str
    session_token: str
    expires_at: int


class SessionTickets:
    def __init__(self, secret: str, lifetime: int = 86400):
        if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
            raise ValueError("Session signing key must have at least 32 bytes")
        if not isinstance(lifetime, int) or not 60 <= lifetime <= 604800:
            raise ValueError("Session lifetime must be 60–604800 seconds")
        self._key = secret.encode("utf-8")
        self._lifetime = lifetime

    def issue(self, tenant_id: str) -> IssuedSession:
        now = int(time.time())
        sid = secrets.token_urlsafe(32)
        expires_at = now + self._lifetime
        payload = _encode(json.dumps(
            {"v": 1, "tid": tenant_id, "sid": sid, "exp": expires_at},
            separators=(",", ":"), sort_keys=True,
        ).encode("utf-8"))
        sig = _encode(hmac.new(self._key, payload.encode("ascii"), hashlib.sha256).digest())
        return IssuedSession(sid, f"{payload}.{sig}", expires_at)

    def verify(self, ticket: str | None, tenant_id: str) -> str:
        try:
            if not isinstance(ticket, str) or len(ticket) > 2048:
                raise InvalidSession("Invalid session credential")
            payload, sig = ticket.split(".")
            expected = hmac.new(self._key, payload.encode("ascii"), hashlib.sha256).digest()
            if not hmac.compare_digest(_decode(sig), expected):
                raise InvalidSession("Invalid session credential")
            claims = json.loads(_decode(payload))
            if (not isinstance(claims, dict) or set(claims) != {"v", "tid", "sid", "exp"}
                    or type(claims["v"]) is not int or claims["v"] != 1
                    or not isinstance(claims["tid"], str)
                    or not isinstance(claims["sid"], str) or len(claims["sid"]) > 128
                    or type(claims["exp"]) is not int
                    or claims["tid"] != tenant_id or claims["exp"] <= int(time.time())):
                raise InvalidSession("Invalid session credential")
            return claims["sid"]
        except (ValueError, TypeError, KeyError, UnicodeError, AttributeError) as exc:
            raise InvalidSession("Invalid session credential") from exc

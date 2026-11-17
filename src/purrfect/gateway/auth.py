"""Application identity boundary: interchangeable verifier, rotating static dev grants.

The static registry is a development credential source, not an identity provider.
It stores only SHA-256 digests of presented bearer secrets in memory.
"""
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Protocol

from purrfect.core.contracts import TenantContext


class ClientVerifier(Protocol):
    def resolve(self, authorization: str | None) -> TenantContext | None: ...


@dataclass(frozen=True)
class ClientCredential:
    fingerprint: bytes
    tenant: TenantContext
    not_before: int | None = None
    expires_at: int | None = None
    disabled: bool = False


class CredentialRegistry:
    def __init__(self, credentials: tuple[ClientCredential, ...]):
        if not credentials or len({c.fingerprint for c in credentials}) != len(credentials):
            raise ValueError("Missing or duplicate client tokens")
        self._credentials = credentials

    @classmethod
    def from_json(cls, raw: str):
        entries = json.loads(raw)
        if not isinstance(entries, list) or not entries:
            raise ValueError("PURR_CLIENTS_JSON must be a nonempty array")
        clients = []
        allowed = {"token", "tenant_id", "products", "not_before", "expires_at", "disabled"}
        for entry in entries:
            if not isinstance(entry, dict) or not {"token", "tenant_id", "products"} <= set(entry) or set(entry) - allowed:
                raise ValueError("Invalid client configuration")
            token, tenant, products = entry["token"], entry["tenant_id"], entry["products"]
            if not isinstance(token, str) or len(token) < 16 or not isinstance(tenant, str) or not tenant or "/" in tenant:
                raise ValueError("Invalid client identity")
            if (not isinstance(products, list) or any(not isinstance(p, str) or not p or "/" in p for p in products)
                    or len(products) != len(set(products))):
                raise ValueError("Invalid product grants")
            before, expiry, disabled = (entry.get("not_before"), entry.get("expires_at"), entry.get("disabled", False))
            if (before is not None and (type(before) is not int or before < 0)
                    or expiry is not None and (type(expiry) is not int or expiry < 0)
                    or before is not None and expiry is not None and before >= expiry
                    or type(disabled) is not bool):
                raise ValueError("Invalid credential lifecycle")
            clients.append(ClientCredential(
                hashlib.sha256(token.encode("utf-8")).digest(),
                TenantContext(tenant, frozenset(products)), before, expiry, disabled,
            ))
        return cls(tuple(clients))

    def resolve(self, authorization: str | None) -> TenantContext | None:
        token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        if not token or len(token) > 4096:
            return None
        fingerprint = hashlib.sha256(token.encode("utf-8")).digest()
        now = int(time.time())
        match = None
        for client in self._credentials:
            if hmac.compare_digest(fingerprint, client.fingerprint):
                if (not client.disabled
                        and (client.not_before is None or now >= client.not_before)
                        and (client.expires_at is None or now < client.expires_at)):
                    match = client.tenant
        return match

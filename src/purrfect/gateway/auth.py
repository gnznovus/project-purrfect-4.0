"""Static development credential registry. Replace with managed identity in production."""
import json
import secrets
from dataclasses import dataclass

from purrfect.core.contracts import TenantContext

@dataclass(frozen=True)
class ClientCredential:
    token: str
    tenant: TenantContext

class CredentialRegistry:
    def __init__(self, credentials: tuple[ClientCredential, ...]):
        if not credentials or len({c.token for c in credentials}) != len(credentials):
            raise ValueError("Missing or duplicate client tokens")
        self._credentials = credentials

    @classmethod
    def from_json(cls, raw: str):
        entries = json.loads(raw)
        if not isinstance(entries, list) or not entries:
            raise ValueError("PURR_CLIENTS_JSON must be a nonempty array")
        clients = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"token", "tenant_id", "products"}:
                raise ValueError("Invalid client configuration")
            token, tenant, products = entry["token"], entry["tenant_id"], entry["products"]
            if not isinstance(token, str) or len(token) < 16 or not isinstance(tenant, str) or not tenant or "/" in tenant:
                raise ValueError("Invalid client identity")
            if (not isinstance(products, list) or any(not isinstance(p, str) or not p or "/" in p for p in products)
                    or len(products) != len(set(products))):
                raise ValueError("Invalid product grants")
            clients.append(ClientCredential(token, TenantContext(tenant, frozenset(products))))
        return cls(tuple(clients))

    def resolve(self, authorization: str | None) -> TenantContext | None:
        token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        result = None
        # Compare against all credentials to avoid exposing which token matched.
        for client in self._credentials:
            if secrets.compare_digest(token, client.token):
                result = client.tenant
        return result

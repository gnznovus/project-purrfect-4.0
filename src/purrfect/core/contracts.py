"""Stable internal contracts. No web or inference-framework dependencies."""
from dataclasses import dataclass

@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    allowed_products: frozenset[str]

@dataclass(frozen=True)
class ChatCommand:
    session_id: str
    message: str
    product_id: str | None = None
    product_version: str | None = None

@dataclass(frozen=True)
class Source:
    id: str
    source: str
    product_id: str

@dataclass(frozen=True)
class ChatResult:
    session_id: str
    status: str
    message: str
    sources: tuple[Source, ...] = ()

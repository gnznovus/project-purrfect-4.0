"""Sophira-owned, transport-neutral approved knowledge contracts.

No database, network, publication endpoint, or automatic approval in this slice.
The in-process catalog is a development fixture, NOT persistent production storage.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Protocol


def _required(value: str):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Nonempty string required")


@dataclass(frozen=True)
class KnowledgeItem:
    id: str
    content: str
    source: str
    entry_revision: int | None = None
    change_note: str | None = None

    def __post_init__(self):
        for value in (self.id, self.content, self.source):
            _required(value)
        if self.entry_revision is not None and (type(self.entry_revision) is not int or self.entry_revision < 1):
            raise ValueError("Invalid knowledge entry revision")
        if self.change_note is not None and (not isinstance(self.change_note, str) or not self.change_note.strip()):
            raise ValueError("Invalid knowledge change note")
        if self.change_note is not None and self.entry_revision is None:
            raise ValueError("Changelog requires an entry revision")

    def payload(self):
        values = [self.id, self.content, self.source]
        if self.entry_revision is not None:
            values.extend((self.entry_revision, self.change_note))
        return values


@dataclass(frozen=True)
class KnowledgePackage:
    product_id: str
    product_version: str
    revision: int
    items: tuple[KnowledgeItem, ...]
    contract_version: int = 1

    def __post_init__(self):
        _required(self.product_id)
        _required(self.product_version)
        if self.contract_version != 1 or type(self.revision) is not int or self.revision < 1:
            raise ValueError("Unsupported package revision or contract")
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("Duplicate knowledge IDs")

    @property
    def digest(self) -> str:
        payload = [self.product_id, self.product_version, self.revision,
                   self.contract_version, [i.payload() for i in sorted(self.items, key=lambda i: i.id)]]
        return sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class KnowledgeDelta:
    product_id: str
    product_version: str
    from_revision: int
    to_revision: int
    upserts: tuple[KnowledgeItem, ...]
    removed_ids: tuple[str, ...]
    target_digest: str
    contract_version: int = 1

    def __post_init__(self):
        _required(self.product_id)
        _required(self.product_version)
        if self.contract_version != 1 or type(self.from_revision) is not int or type(self.to_revision) is not int or not 1 <= self.from_revision < self.to_revision:
            raise ValueError("Invalid delta revisions")
        if len(set(self.removed_ids)) != len(self.removed_ids) or any(not isinstance(i, str) or not i for i in self.removed_ids):
            raise ValueError("Invalid removals")
        ids = [item.id for item in self.upserts]
        if len(set(ids)) != len(ids) or set(ids) & set(self.removed_ids):
            raise ValueError("Conflicting delta operations")
        if len(self.target_digest) != 64 or any(x not in "0123456789abcdef" for x in self.target_digest):
            raise ValueError("Invalid target digest")


def diff(old: KnowledgePackage, new: KnowledgePackage) -> KnowledgeDelta:
    if (old.product_id, old.product_version, old.contract_version) != (
        new.product_id, new.product_version, new.contract_version
    ) or new.revision <= old.revision:
        raise ValueError("Incompatible or non-forward revision")
    before = {i.id: i for i in old.items}
    after = {i.id: i for i in new.items}
    return KnowledgeDelta(
        old.product_id, old.product_version, old.revision, new.revision,
        tuple(item for item in new.items if before.get(item.id) != item),
        tuple(i for i in before if i not in after), new.digest
    )


def apply_delta(current: KnowledgePackage, delta: KnowledgeDelta) -> KnowledgePackage:
    if (current.product_id, current.product_version, current.revision, current.contract_version) != (
        delta.product_id, delta.product_version, delta.from_revision, delta.contract_version
    ):
        raise ValueError("Stale or incompatible knowledge lease")
    items = {item.id: item for item in current.items}
    for identifier in delta.removed_ids:
        if identifier not in items:
            raise ValueError("Unknown tombstone")
        del items[identifier]
    for item in delta.upserts:
        items[item.id] = item
    candidate = KnowledgePackage(
        current.product_id, current.product_version, delta.to_revision,
        tuple(sorted(items.values(), key=lambda i: i.id)), current.contract_version
    )
    if candidate.digest != delta.target_digest:
        raise ValueError("Knowledge checksum mismatch")
    return candidate


class SophiraClient(Protocol):
    def latest(self, product_id: str, product_version: str) -> int | None: ...
    def lease(self, product_id: str, product_version: str,
              revision: int | None = None) -> KnowledgePackage | KnowledgeDelta | None: ...


class SophiraCatalog:
    """In-memory approved revisions used to exercise the standalone boundary.

    publish_approved is a trusted operator/fixture entrypoint, never a Child
    endpoint. A real Sophira service must enforce authentication and approval.
    """
    def __init__(self):
        self._history: dict[tuple[str, str], list[KnowledgePackage]] = {}

    def publish_approved(self, package: KnowledgePackage, *, approved: bool = False):
        if approved is not True:
            raise PermissionError("Explicit approval required")
        key = (package.product_id, package.product_version)
        history = self._history.setdefault(key, [])
        if history and package.revision != history[-1].revision + 1:
            raise ValueError("Revisions must be sequential")
        if not history and package.revision != 1:
            raise ValueError("Initial revision must be one")
        if history:
            previous = {i.id: i for i in history[-1].items}
            for item in package.items:
                old = previous.get(item.id)
                if item.entry_revision is not None:
                    if old is not None and item.content == old.content and item.source == old.source:
                        if old.entry_revision is not None and item.entry_revision != old.entry_revision:
                            raise ValueError("Unchanged entry cannot advance revision")
                    elif old is not None:
                        if item.change_note is None:
                            raise ValueError("Changed knowledge needs approved change note")
                        if old.entry_revision is not None and item.entry_revision != old.entry_revision + 1:
                            raise ValueError("Entry revision must increment once")
                elif old is not None and old.entry_revision is not None:
                    raise ValueError("Cannot remove existing entry revision metadata")
        history.append(package)

    def latest(self, product_id: str, product_version: str) -> int | None:
        history = self._history.get((product_id, product_version), [])
        return history[-1].revision if history else None

    def lease(self, product_id: str, product_version: str,
              revision: int | None = None) -> KnowledgePackage | KnowledgeDelta | None:
        history = self._history.get((product_id, product_version), [])
        if not history:
            return None
        if revision is None:
            return history[-1]
        if type(revision) is not int or revision < 1:
            raise ValueError("Invalid local revision")
        if revision == history[-1].revision:
            return None
        if revision > history[-1].revision:
            raise ValueError("Local revision is ahead of Sophira")
        old = next((p for p in history if p.revision == revision), None)
        return diff(old, history[-1]) if old else history[-1]


class LocalSophiraClient:
    """Dev-phase adapter: same public contract, no HTTP transport."""
    def __init__(self, service: SophiraCatalog):
        self._service = service

    def latest(self, product_id: str, product_version: str) -> int | None:
        return self._service.latest(product_id, product_version)

    def lease(self, product_id: str, product_version: str,
              revision: int | None = None) -> KnowledgePackage | KnowledgeDelta | None:
        return self._service.lease(product_id, product_version, revision)


class KnowledgeCache:
    """Last-good lease; never mutate it until a full update validates."""
    def __init__(self, product_id: str, product_version: str):
        _required(product_id)
        _required(product_version)
        self.product_id = product_id
        self.product_version = product_version
        self.current: KnowledgePackage | None = None

    def refresh(self, client: SophiraClient) -> bool:
        try:
            revision = self.current.revision if self.current else None
            update = client.lease(self.product_id, self.product_version, revision)
            if update is None:
                return False
            if isinstance(update, KnowledgeDelta):
                if self.current is None:
                    raise ValueError("Delta requires a base package")
                candidate = apply_delta(self.current, update)
            elif isinstance(update, KnowledgePackage):
                candidate = update
                if (candidate.product_id, candidate.product_version) != (
                    self.product_id, self.product_version
                ) or self.current and candidate.revision <= self.current.revision:
                    raise ValueError("Unexpected snapshot identity/revision")
            else:
                raise ValueError("Invalid Sophira response")
            self.current = candidate
            return True
        except (ConnectionError, TimeoutError, ValueError, TypeError):
            return False

    def effective(self, fallback: tuple[KnowledgeItem, ...]) -> tuple[KnowledgeItem, ...]:
        # A verified last-good lease survives Sophira outages.
        return self.current.items if self.current is not None else fallback

"""Purr Core: tenant-bound conversation and Sophia-grounded product guidance."""
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol, TypeVar

from purrfect.core.contracts import ChatCommand, ChatResult, Source, TenantContext
from purrfect.sophira import KnowledgeItem, KnowledgePackage


class TextModel(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


class KnowledgeCatalog(Protocol):
    def lease(self, product_id: str, product_version: str,
              revision: int | None = None) -> KnowledgePackage | None: ...


T = TypeVar("T")


class InferenceScheduler(Protocol):
    async def run(self, tenant: str, operation: Callable[[], Awaitable[T]]) -> T: ...


class EvidenceCache(Protocol):
    def lookup(self, tenant: str, product_id: str, package: KnowledgePackage,
               query: str, retrieve: Callable) -> tuple[KnowledgeItem, ...]: ...


class AccessDenied(Exception):
    """A verified tenant lacks access to this product."""


def _terms(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold())) - {
        "the", "and", "for", "with", "this", "that", "what", "how", "can",
        "you", "please", "help", "about", "my", "your", "is", "do", "to", "a", "i",
    }


def retrieve(package: KnowledgePackage, query: str, limit: int = 3):
    terms = _terms(query)
    scored = [(len(terms & _terms(item.id + " " + item.content)), item)
              for item in package.items]
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    return tuple(item for overlap, item in scored if overlap > 0)[:limit]


@dataclass
class PurrCore:
    catalog: KnowledgeCatalog | None = None
    model: TextModel | None = None
    scheduler: InferenceScheduler | None = None
    evidence_cache: EvidenceCache | None = None
    history_limit: int = 6
    session_limit: int = 1024
    _sessions: OrderedDict = field(default_factory=OrderedDict, init=False)
    _lock: RLock = field(default_factory=RLock, init=False)

    async def respond(self, tenant: TenantContext, command: ChatCommand) -> ChatResult:
        if not tenant.tenant_id or not isinstance(tenant.allowed_products, frozenset):
            raise ValueError("Invalid verified tenant context")
        if not 1 <= len(command.session_id) <= 128 or not command.message.strip() or len(command.message) > 2000:
            raise ValueError("Invalid message or session")
        if (command.product_id is None) != (command.product_version is None):
            raise ValueError("Product identity must be paired")
        if command.product_id is not None and command.product_id not in tenant.allowed_products:
            raise AccessDenied("Product not authorized")

        key = (tenant.tenant_id, command.session_id)
        evidence = ()
        if command.product_id is not None and self.catalog is not None:
            scoped_id = f"{tenant.tenant_id}/{command.product_id}"
            package = self.catalog.lease(scoped_id, command.product_version)
            if package is not None:
                evidence = (self.evidence_cache.lookup(
                    tenant.tenant_id, command.product_id, package, command.message, retrieve)
                    if self.evidence_cache else retrieve(package, command.message))
        sources = tuple(Source(item.id, item.source, command.product_id) for item in evidence)
        with self._lock:
            previous = tuple(self._sessions.get(key, ()))

        if command.product_id is not None and not evidence:
            answer = "I don't have verified guidance for that question yet. Could you clarify what you're trying to do?"
            status = "knowledge_gap"
        elif self.model is not None:
            citations = "\n".join(f"[{item.id}] {item.content}" for item in evidence)
            history = "\n".join(f"User: {question}\nPurr: {reply}" for question, reply in previous)
            system = ("You are Purr, a natural, concise product assistant. "
                      "For product questions use only approved excerpts. "
                      "Never invent product facts, steps, or sources. Otherwise chat naturally.")
            prompt = f"History:\n{history}\nApproved excerpts:\n{citations}\nUser: {command.message}"
            async def generate():
                return await self.model.complete(system, prompt)
            answer = (await self.scheduler.run(tenant.tenant_id, generate)
                      if self.scheduler is not None else await generate())
            if not isinstance(answer, str) or not answer.strip():
                raise RuntimeError("Inference returned no answer")
            status = "grounded" if command.product_id is not None else "conversation"
        elif command.product_id is not None:
            answer = "\n\n".join(item.content for item in evidence)
            status = "grounded"
        else:
            answer = ("Hi! I'm Purr. What can I help you with?" if _terms(command.message) & {"hi", "hello", "hey"}
                      else "I'm here to help with product questions. Which product are you using?")
            status = "conversation"

        with self._lock:
            history = self._sessions.setdefault(key, [])
            history.append((command.message, answer))
            self._sessions[key] = history[-self.history_limit:]
            self._sessions.move_to_end(key)
            while len(self._sessions) > self.session_limit:
                self._sessions.popitem(last=False)
        return ChatResult(command.session_id, status, answer, sources)

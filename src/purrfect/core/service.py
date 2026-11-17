"""Framework-independent Purr conversation, retrieval, and streaming."""
import asyncio
import re
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from contextlib import AbstractAsyncContextManager
from threading import RLock
from typing import Protocol, TypeVar

from purrfect.core.contracts import ChatCommand, ChatResult, Source, TenantContext
from purrfect.sophira import KnowledgeItem, KnowledgePackage
from purrfect.infrastructure.sessions import MemorySessions


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


class SessionStore(Protocol):
    def read(self, tenant: str, session: str) -> tuple[tuple[str, str], ...]: ...
    def append(self, tenant: str, session: str, question: str, answer: str) -> None: ...


class SessionCoordinator(Protocol):
    def lock(self, tenant: str, session: str) -> AbstractAsyncContextManager[None]: ...


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
    sessions: SessionStore = field(default_factory=MemorySessions)
    session_coordinator: SessionCoordinator | None = None
    _locks: weakref.WeakValueDictionary = field(default_factory=weakref.WeakValueDictionary, init=False)
    _guard: RLock = field(default_factory=RLock, init=False)

    def _session_lock(self, tenant: str, session: str) -> AbstractAsyncContextManager:
        if self.session_coordinator is not None:
            return self.session_coordinator.lock(tenant, session)
        key = (tenant, session)
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    def _prepare(self, tenant: TenantContext, command: ChatCommand):
        if (not isinstance(tenant.tenant_id, str) or not tenant.tenant_id or
                not isinstance(tenant.allowed_products, frozenset)):
            raise ValueError("Invalid verified tenant context")
        if (not isinstance(command.session_id, str) or not 1 <= len(command.session_id) <= 128
                or not isinstance(command.message, str) or not command.message.strip()
                or len(command.message) > 2000):
            raise ValueError("Invalid message or session")
        if (command.product_id is None) != (command.product_version is None):
            raise ValueError("Product identity must be paired")
        if command.product_id is not None and command.product_id not in tenant.allowed_products:
            raise AccessDenied("Product not authorized")
        evidence = ()
        if command.product_id is not None and self.catalog is not None:
            scoped_id = f"{tenant.tenant_id}/{command.product_id}"
            package = self.catalog.lease(scoped_id, command.product_version)
            if package is not None:
                evidence = (self.evidence_cache.lookup(
                    tenant.tenant_id, command.product_id, package, command.message, retrieve)
                    if self.evidence_cache else retrieve(package, command.message))
        sources = tuple(Source(item.id, item.source, command.product_id) for item in evidence)
        return evidence, sources

    async def _prompt(self, tenant: TenantContext, command: ChatCommand, evidence):
        previous = await asyncio.to_thread(self.sessions.read, tenant.tenant_id, command.session_id)
        citations = "\n".join(f"[{item.id}] {item.content}" for item in evidence)
        history = "\n".join(f"User: {question}\nPurr: {reply}" for question, reply in previous)
        system = ("You are Purr, a natural, concise product assistant. "
                  "For product questions use only approved excerpts. "
                  "Never invent product facts, steps, or sources. Otherwise chat naturally.")
        return system, f"History:\n{history}\nApproved excerpts:\n{citations}\nUser: {command.message}"

    @staticmethod
    def _fallback(command: ChatCommand, evidence):
        if command.product_id is not None and not evidence:
            return "I don't have verified guidance for that question yet. Could you clarify what you're trying to do?", "knowledge_gap"
        if command.product_id is not None:
            return "\n\n".join(item.content for item in evidence), "grounded"
        answer = ("Hi! I'm Purr. What can I help you with?" if _terms(command.message) & {"hi", "hello", "hey"}
                  else "I'm here to help with product questions. Which product are you using?")
        return answer, "conversation"

    async def respond(self, tenant: TenantContext, command: ChatCommand) -> ChatResult:
        async with self._session_lock(tenant.tenant_id, command.session_id):
            evidence, sources = self._prepare(tenant, command)
            if command.product_id is not None and not evidence or self.model is None:
                answer, status = self._fallback(command, evidence)
            else:
                system, prompt = await self._prompt(tenant, command, evidence)
                async def generate():
                    return await self.model.complete(system, prompt)
                answer = (await self.scheduler.run(tenant.tenant_id, generate)
                          if self.scheduler is not None else await generate())
                if not isinstance(answer, str) or not answer.strip():
                    raise RuntimeError("Inference returned no answer")
                status = "grounded" if command.product_id is not None else "conversation"
            await asyncio.to_thread(self.sessions.append, tenant.tenant_id, command.session_id, command.message, answer)
            return ChatResult(command.session_id, status, answer, sources)

    async def stream(self, tenant: TenantContext, command: ChatCommand) -> AsyncIterator[dict]:
        """Yield domain events; Gateway alone chooses SSE framing.

        Only completed responses are committed to session state. Cancellation
        discards partial messages and releases the inference permit.
        """
        async with self._session_lock(tenant.tenant_id, command.session_id):
            evidence, sources = self._prepare(tenant, command)
            status = "grounded" if command.product_id is not None else "conversation"
            if (command.product_id is not None and not evidence) or self.model is None:
                answer, status = self._fallback(command, evidence)
                yield {"event": "delta", "data": {"text": answer}}
            else:
                system, prompt = await self._prompt(tenant, command, evidence)
                fragments: list[str] = []
                queue: asyncio.Queue = asyncio.Queue(maxsize=16)
                terminal = object()

                async def produce():
                    try:
                        async def generate():
                            streaming = getattr(self.model, "stream", None)
                            if streaming is None:
                                text = await self.model.complete(system, prompt)
                                await queue.put(text)
                            else:
                                async for text in streaming(system, prompt):
                                    await queue.put(text)
                        if self.scheduler:
                            await self.scheduler.run(tenant.tenant_id, generate)
                        else:
                            await generate()
                    except Exception as exc:
                        await queue.put(exc)
                    finally:
                        await queue.put(terminal)

                task = asyncio.create_task(produce())
                try:
                    while True:
                        item = await queue.get()
                        if item is terminal:
                            break
                        if isinstance(item, Exception):
                            raise item
                        if not isinstance(item, str):
                            raise RuntimeError("Model returned non-text stream")
                        if item:
                            fragments.append(item)
                            yield {"event": "delta", "data": {"text": item}}
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                answer = "".join(fragments)
                if not answer.strip():
                    raise RuntimeError("Inference returned no answer")
            await asyncio.to_thread(self.sessions.append, tenant.tenant_id, command.session_id, command.message, answer)
            yield {"event": "done", "data": {
                "session_id": command.session_id, "status": status,
                "sources": [{"id": s.id, "source": s.source, "product_id": s.product_id} for s in sources],
            }}

"""Frontend-independent Purr chat and approved Sophia retrieval."""
import asyncio
import re
from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol
from purrfect.sophira_storage import DurableSophira

class TextModel(Protocol):
    async def complete(self, system: str, user: str) -> str: ...

def terms(text):
    return set(re.findall(r"\w+", text.casefold())) - {"the", "and", "for", "with", "this", "that", "what", "how", "can", "you", "please", "help", "about", "my", "your", "is", "do", "to", "a", "i"}

@dataclass
class Purr:
    catalog: DurableSophira | None = None
    model: TextModel | None = None
    sessions: dict = field(default_factory=dict)
    lock: RLock = field(default_factory=RLock)

    def respond(self, request):
        if not isinstance(request, dict) or set(request) - {"session_id", "message", "product_id", "product_version"}:
            raise ValueError("Invalid request")
        session, message = request.get("session_id"), request.get("message")
        pid, version = request.get("product_id"), request.get("product_version")
        if not isinstance(session, str) or not 1 <= len(session) <= 128:
            raise ValueError("Invalid session_id")
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
            raise ValueError("Invalid message")
        if (pid is None) != (version is None):
            raise ValueError("product_id and product_version must be provided together")
        if pid is not None and (not isinstance(pid, str) or not isinstance(version, str) or not 1 <= len(pid) <= 128 or not 1 <= len(version) <= 128):
            raise ValueError("Invalid product identity")
        evidence = []
        if pid is not None and self.catalog:
            package = self.catalog.lease(pid, version)
            if package:
                query_terms = terms(message)
                scored = [(len(query_terms & terms(item.id + " " + item.content)), item) for item in package.items]
                scored.sort(key=lambda x: (-x[0], x[1].id))
                evidence = [item for score, item in scored if score > 0][:3]
        sources = [{"id": item.id, "source": item.source, "product_id": pid} for item in evidence]
        with self.lock:
            previous = tuple(self.sessions.get(session, ())[-6:])
        if pid is not None and not evidence:
            answer = "I don't have verified guidance for that question yet. Could you clarify what you're trying to do?"
            status = "knowledge_gap"
        elif self.model is not None:
            context = "\n".join(f"[{item.id}] {item.content}" for item in evidence)
            history = "\n".join(f"User: {q}\nPurr: {a}" for q, a in previous)
            system = "You are Purr, a natural, concise product assistant. For product questions use only approved excerpts. Never invent product facts, steps or sources. Otherwise chat naturally."
            answer = asyncio.run(self.model.complete(system, f"History:\n{history}\nApproved excerpts:\n{context}\nUser: {message}"))
            status = "grounded" if pid else "conversation"
        elif pid is not None:
            answer = "\n\n".join(item.content for item in evidence)
            status = "grounded"
        else:
            answer = "Hi! I'm Purr. What can I help you with?" if terms(message) & {"hi", "hello", "hey"} else "I'm here to help with product questions. Which product are you using?"
            status = "conversation"
        with self.lock:
            self.sessions.setdefault(session, []).append((message, answer))
            self.sessions[session] = self.sessions[session][-6:]
        return {"session_id": session, "status": status, "message": answer, "sources": sources}

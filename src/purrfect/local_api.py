"""Local-only HTTP POC. Framework-independent knowledge and scope contracts."""
import json
import os
import asyncio
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import urlparse

from purrfect.brain_scope import select_scope
from purrfect.ollama import OllamaModel
from purrfect.discovery import discover
from purrfect.knowledge import EVERYDAY_WORDPRESS, SiteKnowledge
from purrfect.guidance import GuidanceResponse, InputKind, Interaction, Option


@dataclass
class LocalState:
    sessions: dict = field(default_factory=dict)
    mutex: Lock = field(default_factory=Lock)
    model: object | None = None


def _reply(response: GuidanceResponse, scope: str, sources=()):
    interaction = response.interaction
    return {
        "status": response.status, "scope": scope, "message": response.message,
        "interaction": None if interaction is None else {
            "key": interaction.key, "kind": interaction.kind.value,
            "options": [{"id": o.id, "label": o.label} for o in interaction.options],
        },
        "sources": [{"id": e.id, "source": e.source, "product_id": e.product_id}
                    for e in sources],
    }


def _choose(question: str, selection: str, knowledge: SiteKnowledge):
    if selection == "other":
        return _reply(GuidanceResponse("That is outside my available support.", "unsupported"), "unsupported")
    if selection == "wordpress":
        results = knowledge.search(question, general_wp=True)
        scope = "wordpress"
    elif selection in knowledge.products:
        results = knowledge.search(question, product_ids=(selection,))
        scope = "product"
    else:
        return _clarify(knowledge)
    if not results:
        return _reply(GuidanceResponse("I don't have verified guidance yet. What specifically are you trying to do?", "clarification"), scope)
    return _reply(GuidanceResponse("\n\n".join(e.text for e in results), "grounded"), scope, results)


def _clarify(knowledge: SiteKnowledge):
    options = tuple([Option(p.id, p.id) for p in knowledge.products.values()]
                    + [Option("wordpress", "General WordPress"), Option("other", "Other")])
    return _reply(GuidanceResponse(
        "Which product or WordPress area do you need help with?", "needs_input",
        Interaction(InputKind.SINGLE_SELECT, "support_scope", options),
    ), "clarify")


def respond(payload: dict, state: LocalState) -> dict:
    if not isinstance(payload, dict) or set(payload) != {"session_id", "message", "selection", "inventory"}:
        raise ValueError("Invalid request")
    session_id, message, selection = payload["session_id"], payload["message"], payload["selection"]
    if not isinstance(session_id, str) or not (1 <= len(session_id) <= 128):
        raise ValueError("Invalid session")
    if not isinstance(message, str) or len(message) > 2000:
        raise ValueError("Invalid message")
    if selection is not None and not isinstance(selection, str):
        raise ValueError("Invalid selection")
    snapshot = payload["inventory"]
    result = discover(snapshot)
    knowledge = SiteKnowledge(result.products, EVERYDAY_WORDPRESS)
    # All state is transient in this POC. No cross-site credentials or public API.
    with state.mutex:
        if selection is None:
            if not message.strip():
                raise ValueError("Message required")
            state.sessions[session_id] = message
            if state.model is not None:
                try:
                    decision = asyncio.run(select_scope(state.model, message, knowledge))
                except Exception:
                    # Model availability must not block verified local guidance.
                    decision = None
                if decision is not None:
                    answer = _choose(message, decision, knowledge)
                    if answer["status"] in ("grounded", "unsupported"):
                        answer["routing"] = "brain"
                        return answer
                # Uncertainty, unverified matches and backend errors all clarify.
                answer = _clarify(knowledge)
                answer["routing"] = "brain-clarify"
                return answer
            words = set(message.lower().split())
            hits = [p.id for p in knowledge.products.values()
                    if words & (set(p.id.replace("-", " ").lower().split()) - {"mock", "product", "plugin"})]
            if len(hits) == 1:
                answer = _choose(message, hits[0], knowledge)
                if answer["status"] == "grounded":
                    return answer
            if any(word in words for word in ("login", "password", "cache", "permalink")) and not hits:
                answer = _choose(message, "wordpress", knowledge)
                if answer["status"] == "grounded":
                    return answer
            return _clarify(knowledge)
        previous = state.sessions.get(session_id)
        if previous is None:
            return _reply(GuidanceResponse("The conversation expired. Please ask again.", "clarification"), "clarify")
        return _choose(previous, selection, knowledge)


def serve(host: str = "0.0.0.0", port: int = 8765):
    mode = os.environ.get("PURRA_BRAIN_MODE", "deterministic").lower()
    if mode not in ("deterministic", "ollama"):
        raise ValueError("Invalid PURRA_BRAIN_MODE")
    model = OllamaModel(
        model=os.environ.get("PURRA_OLLAMA_MODEL", "llama3.2:3b"),
        base_url=os.environ.get("PURRA_OLLAMA_URL", "http://ollama:11434"),
        timeout=5.0,
    ) if mode == "ollama" else None
    state = LocalState(model=model)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if urlparse(self.path).path != "/v1/chat":
                self.send_error(404)
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self.send_error(415)
                return
            try:
                count = int(self.headers.get("Content-Length", "0"))
                if not 0 < count <= 65536:
                    raise ValueError("Invalid body length")
                payload = json.loads(self.rfile.read(count))
                output = respond(payload, state)
                code = 200
            except (ValueError, TypeError, KeyError) as error:
                output, code = {"error": str(error)}, 400
            body = json.dumps(output).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve()

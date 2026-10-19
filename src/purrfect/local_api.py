"""Local-only HTTP POC. Framework-independent knowledge and scope contracts."""
import json
import os
import re
from time import perf_counter
from dataclasses import dataclass, field, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

from purrfect.ollama import OllamaModel
from purrfect.conversation import Conversation
from purrfect import troubleshooting as troubleshoot
from purrfect.conversation_intent import heuristic
from purrfect.discovery import discover
from purrfect.knowledge import EVERYDAY_WORDPRESS, SiteKnowledge
from purrfect.guidance import GuidanceResponse, InputKind, Interaction, Option
from purrfect.sophira_bridge import effective_knowledge, sync_request
from purrfect.sophira import LocalSophiraClient
from purrfect.sophira_storage import DurableSophira


@dataclass
class LocalState:
    sessions: dict = field(default_factory=dict)
    workflows: dict = field(default_factory=dict)
    mutex: Lock = field(default_factory=Lock)
    model: object | None = None
    sophira: object | None = None


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


def _procedure_options(pid, knowledge):
    product = knowledge.products.get(pid)
    return tuple(Option(f"troubleshoot:{pid}:{i}", "Troubleshoot: " + procedure.title)
                 for i, procedure in enumerate(product.troubleshooting[:12])) if product else ()


def _troubleshooting_reply(knowledge, workflow):
    result = troubleshoot.current(knowledge, workflow)
    interaction = None
    if result.status == "awaiting_result":
        interaction = Interaction(InputKind.SINGLE_SELECT, "troubleshooting_result", (
            Option(f"check:{result.step_id}:worked", "It worked"),
            Option(f"check:{result.step_id}:failed", "Didn't work"),
            Option(f"check:{result.step_id}:why", "Why this step?"),
        ))
    answer = _reply(GuidanceResponse(result.message, result.status, interaction), "product")
    if result.source:
        answer["sources"] = [{"id": workflow.step_id, "source": result.source,
                              "product_id": workflow.product_id}]
    return answer


def _choose(question: str, selection: str, knowledge: SiteKnowledge):
    if selection == "other":
        return _reply(GuidanceResponse("That is outside my available support.", "unsupported"), "unsupported")
    if selection == "wordpress":
        results = knowledge.search(question, general_wp=True)
        scope = "wordpress"
    elif selection in knowledge.products:
        # Naming a product establishes scope, not evidence for the requested
        # capability. Avoid matching its ID alone to unrelated documentation.
        query = re.sub(r"(?<![\w-])" + re.escape(selection) + r"(?![\w-])", "",
                       question, flags=re.I)
        results = knowledge.search(query, product_ids=(selection,))
        scope = "product"
    else:
        return _clarify(knowledge)
    if not results:
        choices = (knowledge.wordpress if selection == "wordpress"
                   else knowledge.products[selection].evidence)
        options = tuple(Option(f"guide:{selection}:{i}", item.title)
                        for i, item in enumerate(choices[:12]))
        if selection in knowledge.products:
            options += _procedure_options(selection, knowledge)
        if options:
            return _reply(GuidanceResponse(
                "Which documented topic would you like help with?", "needs_input",
                Interaction(InputKind.SINGLE_SELECT, "support_intent", options),
            ), scope)
        return _reply(GuidanceResponse(
            "I don't have verified guidance yet. Could you clarify?", "clarification"), scope)
    procedures = _procedure_options(selection, knowledge) if selection in knowledge.products else ()
    interaction = (Interaction(InputKind.SINGLE_SELECT, "troubleshooting_start", procedures)
                   if procedures else None)
    return _reply(GuidanceResponse("\n\n".join(e.text for e in results), "grounded", interaction), scope, results)


def _is_generic_help(message: str) -> bool:
    """An unspecified request for assistance needs a scope, never 'other'."""
    normalized = re.sub(r"[^a-z0-9 ]", "", message.casefold())
    normalized = " ".join(normalized.split())
    return bool(re.fullmatch(
        r"(?:i need (?:some )?help|help(?: me)?|"
        r"can you help me|i need assistance|please help)"
        r"(?: (?:here|please|with this))?", normalized
    ))


def _clarify(knowledge: SiteKnowledge):
    options = tuple([Option(p.id, p.id) for p in knowledge.products.values()]
                    + [Option("wordpress", "General WordPress"), Option("other", "Other")])
    return _reply(GuidanceResponse(
        "Which product or WordPress area do you need help with?", "needs_input",
        Interaction(InputKind.SINGLE_SELECT, "support_scope", options),
    ), "clarify")


def respond(payload: dict, state: LocalState) -> dict:
    if not isinstance(payload, dict) or not {"session_id", "message", "selection", "inventory"} <= set(payload) or set(payload) - {"session_id", "message", "selection", "inventory", "context", "knowledge_leases", "debug"}:
        raise ValueError("Invalid request")
    session_id, message, selection = payload["session_id"], payload["message"], payload["selection"]
    if not isinstance(session_id, str) or not (1 <= len(session_id) <= 128):
        raise ValueError("Invalid session")
    if not isinstance(message, str) or len(message) > 2000:
        raise ValueError("Invalid message")
    if selection is not None and not isinstance(selection, str):
        raise ValueError("Invalid selection")
    debug = payload.get("debug", False)
    if not isinstance(debug, bool):
        raise ValueError("Invalid debug mode")
    began = perf_counter()
    trace = []
    context = payload.get("context", {})
    snapshot = payload["inventory"]
    result = discover(snapshot)
    knowledge = effective_knowledge(SiteKnowledge(result.products, EVERYDAY_WORDPRESS), payload.get("knowledge_leases", []))
    if not isinstance(context, dict):
        raise ValueError("Invalid browser context")
    if debug:
        trace.append({"stage": "Discovery and knowledge", "ms": round((perf_counter() - began) * 1000, 2)})
    restored = Conversation.restore({k: v for k, v in context.items()
                                     if k != "troubleshooting"}, set(knowledge.products))
    lock_started = perf_counter()
    with state.mutex:
        if debug:
            trace.append({"stage": "Session lock", "ms": round((perf_counter() - lock_started) * 1000, 2)})
        previous = state.sessions.get(session_id)
        # A nonempty browser snapshot can restore context after a Python restart.
        # It cannot authorize product access: _choose always checks fresh registry.
        conversation = restored if previous is None else Conversation.restore(
            previous.export(), set(knowledge.products))
        workflow = state.workflows.get(session_id)
        if workflow is None and context.get("troubleshooting") is not None:
            try:
                workflow = troubleshoot.restore(knowledge, context["troubleshooting"])
            except (ValueError, TypeError, KeyError):
                workflow = None
        if workflow is not None:
            try:
                troubleshoot.current(knowledge, workflow)
            except (ValueError, TypeError, KeyError):
                workflow = None

        def finish(answer, next_state, next_workflow=workflow):
            # A grounded answer can carry a reference, but only currently active
            # registered evidence is allowed to be replayed later.
            if answer.get("sources"):
                item = answer["sources"][0]
                next_state = next_state.updated(topic=next_state.topic, scope=next_state.scope,
                    pending=next_state.pending, evidence_id=item["id"],
                    outcome=next_state.outcome)
            # Retain tasks through chat/clarification, but never attach a task
            # from a different product after a validated scope selection.
            if next_workflow is not None and next_state.scope != next_workflow.product_id:
                next_workflow = None
            state.sessions[session_id] = next_state
            if next_workflow is None:
                state.workflows.pop(session_id, None)
            else:
                state.workflows[session_id] = next_workflow
            answer["context"] = next_state.export()
            if next_workflow is not None:
                answer["context"]["troubleshooting"] = next_workflow.export()
            if debug:
                trace.append({"stage": "Final route", "result": answer.get("routing", answer.get("scope", "unknown")),
                              "status": answer.get("status", "unknown"),
                              "buttons": len((answer.get("interaction") or {}).get("options", [])),
                              "sources": len(answer.get("sources", []))})
                answer["debug"] = {"duration_ms": round((perf_counter() - began) * 1000, 2),
                                   "model_calls": sum(step.get("model_calls", 0) for step in trace),
                                   "stages": trace}
            return answer

        def workflow_response(result):
            if result == "why":
                answer = _troubleshooting_reply(knowledge, workflow)
                answer["message"] = troubleshoot.explain(knowledge, workflow) + "\n\n" + answer["message"]
                return finish(answer, conversation, workflow)
            updated, _ = troubleshoot.advance(knowledge, workflow, result)
            answer = _troubleshooting_reply(knowledge, updated)
            candidate = conversation.updated(topic=conversation.topic, scope=updated.product_id,
                pending=updated.status == "awaiting_result",
                outcome="resolved" if updated.status == "resolved" else "unresolved" if updated.status == "escalation_required" else "open",
                evidence_id=conversation.evidence_id)
            return finish(answer, candidate, updated)

        if selection is not None:
            if selection.startswith("check:"):
                parts = selection.split(":")
                if len(parts) != 3 or parts[2] not in ("worked", "failed", "why") or workflow is None or workflow.status != "awaiting_result" or parts[1] != workflow.step_id:
                    return finish(_reply(GuidanceResponse("That troubleshooting choice is no longer available.", "clarification"), "conversation"), conversation, workflow)
                return workflow_response(parts[2])
            if selection.startswith("troubleshoot:"):
                parts = selection.split(":")
                if len(parts) != 3 or not parts[2].isdigit() or conversation.scope != parts[1] or not conversation.topic:
                    return finish(_clarify(knowledge), conversation)
                product = knowledge.products.get(parts[1])
                index = int(parts[2])
                if product is None or index >= min(len(product.troubleshooting), 12):
                    return finish(_clarify(knowledge), conversation)
                started, _ = troubleshoot.start(knowledge, parts[1], product.troubleshooting[index].id)
                return finish(_troubleshooting_reply(knowledge, started),
                    conversation.updated(topic=conversation.topic, scope=parts[1], pending=True), started)
            if selection.startswith("guide:") and conversation.pending and conversation.topic:
                parts = selection.split(":")
                if len(parts) == 3 and parts[2].isdigit():
                    chosen_scope = parts[1]
                    documents = (knowledge.wordpress if chosen_scope == "wordpress"
                                 else knowledge.products[chosen_scope].evidence
                                 if chosen_scope in knowledge.products else ())
                    index = int(parts[2])
                    if chosen_scope == conversation.scope and 0 <= index < min(len(documents), 12):
                        item = documents[index]
                        answer = _reply(GuidanceResponse(item.text, "grounded"),
                                        "wordpress" if chosen_scope == "wordpress" else "product",
                                        (item,))
                        return finish(answer, conversation.updated(scope=chosen_scope))
                # Reject a forged/stale topic without changing the valid pending scope.
                return finish(_clarify(knowledge), conversation)
            if not conversation.pending or not conversation.topic:
                return finish(_clarify(knowledge), conversation.updated(pending=True))
            if selection not in (set(knowledge.products) | {"wordpress", "other"}):
                return finish(_clarify(knowledge), conversation.updated(pending=True))
            answer = _choose(conversation.topic, selection, knowledge)
            if answer["status"] == "grounded":
                return finish(answer, conversation.updated(scope=selection))
            if answer["status"] == "needs_input":
                return finish(answer, conversation.updated(scope=selection, pending=True))
            if answer["status"] == "unsupported":
                return finish(answer, conversation.updated(scope=None))
            return finish(answer, conversation.updated(scope=None, pending=True))

        if not message.strip():
            raise ValueError("Message required")
        if workflow is not None and workflow.status == "awaiting_result":
            short = re.sub(r"[^a-z0-9 ]", "", message.casefold()).strip()
            if short in ("worked", "it worked", "yes it worked", "fixed", "it is fixed",
                         "didnt work", "it didnt work", "failed", "not working",
                         "still not working", "why this step", "why"):
                result = ("worked" if short in ("worked", "it worked", "yes it worked", "fixed", "it is fixed")
                          else "why" if short in ("why", "why this step") else "failed")
                return workflow_response(result)
        def retained(**changes):
            return replace(conversation, revision=conversation.revision + 1, **changes)

        def previous_guidance(kind):
            docs = (knowledge.wordpress if conversation.scope == "wordpress" else
                    knowledge.products[conversation.scope].evidence
                    if conversation.scope in knowledge.products else ())
            evidence = next((item for item in docs if item.id == conversation.evidence_id), None)
            if kind == "simplify" and evidence is not None:
                return finish(_reply(GuidanceResponse(
                    "The documented instruction is: " + evidence.text, "grounded"),
                    "wordpress" if conversation.scope == "wordpress" else "product", (evidence,)),
                    retained())
            response = ("The registered guide doesn't specify a previous step. "
                        "Which part would you like me to explain?" if kind == "followup" else
                        "Which part of the documented instruction is unclear?")
            return finish(_reply(GuidanceResponse(response, "clarification"), "conversation"), retained())

        fallback = heuristic(message)
        meaning = None
        if state.model is not None:
            # Free text has exactly one inference attempt. Rejected proposals and
            # adapter errors must never fall through to another model handler.
            model_started = perf_counter()
            try:
                from purrfect.stateful_langgraph import understand_message
                registered = {p.id: p.id for p in knowledge.products.values()}
                registered.update(wordpress="General WordPress", other="Other")
                meaning = understand_message(state.model, message, {
                    "topic": conversation.topic, "scope": conversation.scope,
                    "has_evidence": bool(conversation.evidence_id),
                    "outcome": conversation.outcome,
                    "has_active_troubleshooting": workflow is not None,
                }, registered, trace)
                if debug:
                    trace.append({"stage": "Unified decision",
                        "result": meaning["intent"] if meaning else "Invalid output; safe clarification",
                        "ms": round((perf_counter() - model_started) * 1000, 2)})
            except Exception as error:
                if debug:
                    trace.append({"stage": "Unified decision", "result": "Graph error: " + type(error).__name__})
            if meaning is None and fallback is None:
                answer = _clarify(knowledge)
                failed = any(step.get("error") for step in trace)
                answer["routing"] = "brain-unavailable" if failed else "brain-clarify"
                return finish(answer, retained(topic=conversation.topic or message, pending=True))

        if meaning is not None:
            kind = meaning["intent"]
            # Existing deterministic feedback guards retain negation handling.
            # A model alone cannot confirm successful troubleshooting or resolve
            # an issue. Explicit workflow choices are checked above.
            if fallback is not None:
                kind = fallback.kind
            elif kind == "resolved":
                kind = "clarify"
                meaning = dict(meaning, response="Could you confirm whether the issue is fixed?")
            if kind == "social":
                answer = _reply(GuidanceResponse(meaning["response"], "grounded"), "conversation")
                answer["routing"] = "unified-intent"
                return finish(answer, retained())
            if kind in ("help", "clarify"):
                choices = tuple(Option(item["id"], item["label"])
                                for item in meaning["options"] if item["id"] != "other")
                if kind == "help" and not choices:
                    choices = tuple(option for option in _clarify(knowledge)["interaction"]["options"]
                                    if option["id"] != "other")
                    choices = tuple(Option(item["id"], item["label"]) for item in choices[:4])
                interaction = Interaction(InputKind.SINGLE_SELECT, "support_scope", choices) if choices else None
                answer = _reply(GuidanceResponse(meaning["response"],
                    "needs_input" if interaction else "clarification", interaction), "conversation")
                answer["routing"] = "unified-intent"
                # Clarification does not discard evidence, topic or a live task.
                candidate = (retained(pending=bool(interaction)) if conversation.topic else
                    conversation.updated(topic=message, pending=bool(interaction)))
                return finish(answer, candidate)
            if kind in ("product", "wordpress"):
                target = meaning["target"] if kind == "product" else "wordpress"
                reference = re.search(r"\b(?:it|that|those|previous|again|step)\b", message.lower())
                correction = re.search(r"\b(?:i meant|instead|switch to|rather than)\b", message.lower())
                topic = conversation.topic if reference and conversation.topic and not correction else message
                answer = _choose(topic, target, knowledge)
                answer["routing"] = "unified-intent"
                return finish(answer, conversation.updated(topic=topic, scope=target,
                    pending=answer["status"] == "needs_input"),
                    workflow if workflow is not None and workflow.product_id == target else None)
            if kind == "unresolved" and workflow is not None and workflow.status == "awaiting_result":
                return workflow_response("failed")
            if kind == "followup" and workflow is not None and workflow.status == "awaiting_result":
                return workflow_response("why")
            if kind in ("followup", "simplify") and conversation.topic:
                return previous_guidance(kind)
            if kind == "unresolved":
                wording = meaning["response"] or (
                    "What happened when you tried it?" if conversation.evidence_id else
                    "What didn't work? Tell me what you were trying to do.")
                answer = _reply(GuidanceResponse(wording, "clarification"), "conversation")
                answer["routing"] = "unified-intent"
                return finish(answer, retained(outcome="unresolved"))
            # Explicit success and invalid-output feedback use the same existing
            # deterministic implementation below, without another inference.
        else:
            kind = fallback.kind if fallback is not None else "new"

        if kind == "resolved":
            response = ("Glad that worked! Let me know if you need help with anything else."
                        if conversation.evidence_id else "Glad to hear it! What were you working on?")
            return finish(_reply(GuidanceResponse(response, "grounded"), "conversation"),
                retained(outcome="resolved") if conversation.evidence_id else conversation)
        if kind == "unresolved":
            response = ("What didn't work? Tell me what you were trying to do."
                        if not conversation.evidence_id else
                        "What happened when you tried it? Did you see an error message?")
            return finish(_reply(GuidanceResponse(response, "clarification"), "conversation"),
                retained(outcome="unresolved"))
        if conversation.topic and kind in ("simplify", "followup"):
            return previous_guidance(kind)
        if state.model is not None:
            answer = _clarify(knowledge)
            answer["routing"] = "brain-clarify"
            return finish(answer, retained(topic=conversation.topic or message, pending=True))

        # Existing offline deterministic behavior. Normal Ollama conversations
        # never enter a second classifier or a separate conversational draft.
        lowered = re.sub(r"[^a-z0-9 ]", "", message.lower()).strip()
        greeting = lowered in ("hi", "hello", "hey", "hi purra", "hello purra")
        pleasantry = lowered in ("can i ask something else", "can i ask another question",
                                 "thank you", "thanks", "how are you",
                                 "how are you today", "how is your day",
                                 "good morning", "good evening")
        if greeting or pleasantry:
            response = ("Hi! I'm here if you need help with WordPress or your registered products."
                        if greeting else "Of course! What would you like help with?")
            return finish(_reply(GuidanceResponse(response, "grounded"), "conversation"), retained())
        generic_help = (_is_generic_help(message) or bool(re.fullmatch(
            r"(?:i (?:dont|do not) know (?:where|how) to start|"
            r"(?:im|i am) (?:lost|confused)|"
            r"(?:i have no idea|not sure|no idea) (?:where|how) to start|"
            r"what (?:can|should) i do)", lowered)))
        if generic_help:
            return finish(_clarify(knowledge), conversation.updated(topic=message, pending=True))
        correction = re.search(r"\b(?:i meant|instead|switch to|rather than)\b", message.lower())
        reference = re.search(r"\b(?:it|that|those|previous|again|step)\b", message.lower())
        topic = conversation.topic if reference and conversation.topic and not correction else message
        candidate = conversation.updated(topic=topic, scope=None, pending=False)

        words = set(message.lower().split())
        hits = [p.id for p in knowledge.products.values()
                if words & (set(p.id.replace("-", " ").lower().split())
                            - {"mock", "product", "plugin"})]
        if len(hits) == 1:
            answer = _choose(topic, hits[0], knowledge)
            if answer["status"] == "grounded":
                return finish(answer, candidate.updated(scope=hits[0]))
        if any(word in words for word in ("login", "password", "cache", "permalink")) and not hits:
            answer = _choose(topic, "wordpress", knowledge)
            if answer["status"] == "grounded":
                return finish(answer, candidate.updated(scope="wordpress"))
        return finish(_clarify(knowledge), candidate.updated(pending=True))


def _sophira_fault_active() -> bool:
    """Development-only outage injection controlled by container shell, never HTTP."""
    marker = os.environ.get("SOPHIRA_DEV_FAULT_FILE")
    return bool(marker and Path(marker).is_file())


def serve(host: str = "0.0.0.0", port: int = 8765):
    mode = os.environ.get("PURRA_BRAIN_MODE", "deterministic").lower()
    if mode not in ("deterministic", "ollama"):
        raise ValueError("Invalid PURRA_BRAIN_MODE")
    model = OllamaModel(
        model=os.environ.get("PURRA_OLLAMA_MODEL", "llama3.2:3b"),
        base_url=os.environ.get("PURRA_OLLAMA_URL", "http://ollama:11434"),
        timeout=float(os.environ.get("PURRA_OLLAMA_TIMEOUT", "120")),
    ) if mode == "ollama" else None
    sophira_path = os.environ.get("SOPHIRA_DB_PATH")
    sophira = DurableSophira(sophira_path) if sophira_path else None
    state = LocalState(model=model, sophira=sophira)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/v1/health":
                result = {"service": "purra", "status": "healthy"}
                code = 200
            elif path == "/v1/knowledge/health":
                healthy = state.sophira is not None and not _sophira_fault_active()
                if healthy:
                    try:
                        state.sophira.latest("__purrfect_health_probe__", "0")
                    except (OSError, ValueError):
                        healthy = False
                result = {"service": "sophira", "status": "healthy" if healthy else "unavailable"}
                code = 200 if healthy else 503
            else:
                self.send_error(404)
                return
            body = json.dumps(result).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            path = urlparse(self.path).path
            if path not in ("/v1/chat", "/v1/knowledge/sync"):
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
                if path == "/v1/knowledge/sync":
                    if _sophira_fault_active():
                        raise ConnectionError("Sophira temporarily unavailable (development fault injection)")
                    if state.sophira is None:
                        raise ValueError("Sophira not configured")
                    output = sync_request(LocalSophiraClient(state.sophira), payload)
                else:
                    output = respond(payload, state)
                code = 200
            except ConnectionError:
                output, code = {"error": "Sophira temporarily unavailable"}, 503
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

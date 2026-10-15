"""Adaptive, LLM-assisted routing over product-owned guidance contracts.

No product operation is available from this module. LLM suggestions must match
advertised objective IDs, known field keys and validated input values.
"""

import json
from dataclasses import dataclass
from typing import Literal

from purrfect.brain import ProductObjective, TextModel
from purrfect.guidance import GuidanceResponse, GuidanceSession
from purrfect.stateful import Turn
from purrfect.stateful_custom import CustomConversation


@dataclass(frozen=True)
class Route:
    kind: Literal["continue", "correct", "switch", "clarify"]
    key: str | None = None
    value: str | tuple[str, ...] | None = None
    objective_id: str | None = None


class AdaptiveGuide:
    """One-session coordinator using either conversation implementation.

    Session bindings are experimental in-memory coordination, not durable
    cross-process storage. The underlying engines retain their own state.
    """

    def __init__(self, model: TextModel, objectives: tuple[ProductObjective, ...],
                 engine_type=CustomConversation):
        ids = [item.id for item in objectives]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("A unique, nonempty product objective catalog is required")
        self.model = model
        self.catalog = {item.id: item for item in objectives}
        self.engines = {item.id: engine_type(item.guidance) for item in objectives}
        self.current: dict[str, str] = {}

    def _get(self, session_id: str):
        if not session_id or session_id not in self.current:
            raise ValueError("Unknown conversation; start first")
        objective_id = self.current[session_id]
        return objective_id, self.engines[objective_id]

    async def start(self, session_id: str, message: str) -> GuidanceResponse:
        if not session_id or not message.strip():
            raise ValueError("Session and request must not be empty")
        if session_id in self.current:
            raise ValueError("Conversation already started")
        raw = await self.model.complete(
            "Select the matching objective_id from the provided catalog. "
            "Return JSON with only objective_id, or null if unsupported.",
            json.dumps({"message": message, "objectives": [
                {"id": item.id, "description": item.guidance.objective}
                for item in self.catalog.values()
            ]}),
        )
        data = self._parse(raw)
        identifier = data.get("objective_id") if set(data) == {"objective_id"} else None
        if not isinstance(identifier, str) or identifier not in self.catalog:
            return self._clarify("I couldn't match that request to available product guidance.")
        result = self.engines[identifier].send(session_id, Turn("start"))
        self.current[session_id] = identifier
        return result

    async def message(self, session_id: str, message: str) -> GuidanceResponse:
        if not message.strip():
            raise ValueError("Message cannot be empty")
        objective_id, engine = self._get(session_id)
        # Product state, not the model, supplies every permissible input.
        state = self._state(engine, session_id)
        guidance = self.catalog[objective_id].guidance
        raw = await self.model.complete(
            "Choose exactly one route from continue, correct, switch, clarify. "
            "Return JSON keys: kind and optionally key, value, objective_id. "
            "Only use keys and objective IDs in the provided context. "
            "If ambiguous, return clarify. Do not invent targets or capabilities.",
            json.dumps({
                "message": message,
                "current_objective": objective_id,
                "current_answers": state,
                "pending_key": self._pending(guidance, state),
                "available_objectives": list(self.catalog),
                "allowed_fields": [item.key for item in guidance.requirements],
            }),
        )
        try:
            data = self._parse(raw)
            route = self._route(data)
            if route.kind == "clarify":
                return self._clarify("Could you clarify what you'd like to change or select?")
            if route.kind == "switch":
                return self._switch(session_id, objective_id, route.objective_id, state)
            if route.key is None or route.value is None:
                raise ValueError("Missing field/value")
            return engine.send(session_id, Turn(
                "answer" if route.kind == "continue" else "correct",
                route.key, route.value,
            ))
        except (TypeError, ValueError, KeyError):
            return self._clarify("I couldn't safely determine the next step. Please clarify.")

    def _switch(self, session_id: str, current_id: str, new_id: str | None,
                old_answers: dict) -> GuidanceResponse:
        if not new_id or new_id not in self.catalog or new_id == current_id:
            raise ValueError("Unsupported objective switch")
        old_requirements = {r.key: r for r in self.catalog[current_id].guidance.requirements}
        new_definition = self.catalog[new_id].guidance
        candidate = GuidanceSession(new_definition)
        reusable = []
        for requirement in new_definition.requirements:
            original = old_requirements.get(requirement.key)
            if (original is None or original.kind != requirement.kind
                    or requirement.key not in old_answers):
                break
            try:
                candidate.submit(requirement.key, old_answers[requirement.key])
            except ValueError:
                break
            reusable.append((requirement.key, old_answers[requirement.key]))

        # Switch only after all validations; never overwrite a previously
        # initialized target session.
        new_engine = self.engines[new_id]
        response = new_engine.send(session_id, Turn("start"))
        for key, value in reusable:
            response = new_engine.send(session_id, Turn("answer", key, value))
        self.current[session_id] = new_id
        return response

    @staticmethod
    def _parse(raw: str) -> dict:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _route(data: dict) -> Route:
        if not set(data).issubset({"kind", "key", "value", "objective_id"}):
            raise ValueError("Extra model fields")
        kind = data.get("kind")
        if kind not in ("continue", "correct", "switch", "clarify"):
            raise ValueError("Unknown route")
        value = data.get("value")
        if isinstance(value, list) and all(isinstance(x, str) for x in value):
            value = tuple(value)
        if value is not None and not isinstance(value, (str, tuple)):
            raise ValueError("Invalid answer type")
        return Route(kind, data.get("key"), value, data.get("objective_id"))

    @staticmethod
    def _pending(definition, answers):
        return next((r.key for r in definition.requirements if r.key not in answers), None)

    @staticmethod
    def _state(engine, session_id):
        # Both experimental adapters expose their own checkpoint readers.
        if hasattr(engine, "_load"):
            return dict(engine._load(session_id).answers)
        snapshot = engine.graph.get_state(
            {"configurable": {"thread_id": session_id}}
        )
        return dict(snapshot.values.get("answers", {}))

    @staticmethod
    def _clarify(message: str) -> GuidanceResponse:
        return GuidanceResponse(message=message, status="clarification")

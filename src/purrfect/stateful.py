"""Pure, framework-independent conversation transitions for the 1.3 experiment."""

from dataclasses import dataclass, field, replace
from typing import Literal

from purrfect.guidance import GuidanceDefinition, GuidanceSession, GuidanceResponse


@dataclass(frozen=True)
class Turn:
    kind: Literal["start", "answer", "correct"]
    key: str | None = None
    value: str | tuple[str, ...] | None = None


@dataclass(frozen=True)
class TaskState:
    answers: dict[str, str | tuple[str, ...]] = field(default_factory=dict)
    started: bool = False


def advance(
    definition: GuidanceDefinition, state: TaskState, turn: Turn
) -> tuple[TaskState, GuidanceResponse]:
    """Revalidate every retained answer against product-owned requirements."""
    if turn.kind == "start":
        if state.started:
            raise ValueError("Task already started")
        new_state = TaskState(started=True)
    else:
        if not state.started:
            raise ValueError("Start the task first")
        if turn.key is None or turn.value is None:
            raise ValueError("Answer requires a key and value")
        keys = [item.key for item in definition.requirements]
        if turn.key not in keys:
            raise ValueError("Unknown target")
        if turn.kind == "answer":
            session = hydrate(definition, state)
            if session.current().interaction is None or session.current().interaction.key != turn.key:
                raise ValueError("Answer must match the pending target")
            response = session.submit(turn.key, turn.value)
            return TaskState(dict(response.resolved), True), response
        if turn.kind != "correct":
            raise ValueError("Unknown event")
        if turn.key not in state.answers:
            raise ValueError("Only answered fields can be corrected")
        index = keys.index(turn.key)
        kept = {key: value for key, value in state.answers.items() if keys.index(key) < index}
        session = hydrate(definition, TaskState(kept, True))
        response = session.submit(turn.key, turn.value)
        return TaskState(dict(response.resolved), True), response
    return new_state, hydrate(definition, new_state).current()


def hydrate(definition: GuidanceDefinition, state: TaskState) -> GuidanceSession:
    session = GuidanceSession(definition)
    for requirement in definition.requirements:
        if requirement.key not in state.answers:
            break
        session.submit(requirement.key, state.answers[requirement.key])
    if len(session.current().resolved) != len(state.answers):
        raise ValueError("Saved context contains unknown or out-of-order answers")
    return session

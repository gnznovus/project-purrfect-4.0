"""Minimal in-process reference implementation for Goal 1.3."""

from purrfect.guidance import GuidanceDefinition
from purrfect.stateful import TaskState, Turn, advance


class CustomConversation:
    def __init__(self, definition: GuidanceDefinition):
        self.definition = definition
        self.sessions: dict[str, TaskState] = {}

    def send(self, session_id: str, turn: Turn):
        state = self.sessions.get(session_id, TaskState())
        updated, response = advance(self.definition, state, turn)
        self.sessions[session_id] = updated
        return response

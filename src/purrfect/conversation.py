"""Recoverable support-conversation state.

Only user intent/topic are restored. Product availability and knowledge remain
authoritative from the current WordPress discovery snapshot.
"""
from dataclasses import dataclass

ALLOWED_SCOPES = {"wordpress", "other"}

@dataclass(frozen=True)
class Conversation:
    topic: str = ""
    scope: str | None = None
    pending: bool = False
    revision: int = 0

    @classmethod
    def restore(cls, raw: dict, available: set[str]) -> "Conversation":
        if not isinstance(raw, dict) or set(raw) - {"last_question", "last_scope", "pending", "revision"}:
            raise ValueError("Invalid conversation context")
        topic = raw.get("last_question", "")
        scope = raw.get("last_scope")
        pending = raw.get("pending", False)
        revision = raw.get("revision", 0)
        if not isinstance(topic, str) or len(topic) > 2000:
            raise ValueError("Invalid conversation topic")
        if scope is not None and not isinstance(scope, str):
            raise ValueError("Invalid conversation scope")
        if not isinstance(pending, bool) or type(revision) is not int or not 0 <= revision <= 1000000:
            raise ValueError("Invalid conversation state")
        # An inactive product must never be reinstated by browser state.
        if scope not in available | ALLOWED_SCOPES:
            scope = None
            pending = bool(topic)
        return cls(topic, scope, pending, revision)

    def updated(self, *, topic=None, scope=None, pending=False):
        return Conversation(self.topic if topic is None else topic, scope, pending, self.revision + 1)

    def export(self):
        return {
            "last_question": self.topic,
            "last_scope": self.scope,
            "pending": self.pending,
            "revision": self.revision,
        }

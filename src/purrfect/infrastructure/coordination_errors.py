"""Provider-independent distributed coordination errors."""


class SessionBusy(Exception):
    """Another worker holds this conversation session."""


class SessionLeaseLost(Exception):
    """Conversation lease expired or was replaced."""


class GlobalInferenceLeaseLost(Exception):
    """Global inference permit was lost during generation."""

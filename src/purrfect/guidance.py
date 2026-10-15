"""Deterministic, product-grounded guidance contracts (no LLM or execution)."""

from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlsplit


class InputKind(StrEnum):
    URL = "url"
    SINGLE_SELECT = "single_select"
    MULTI_SELECT = "multi_select"


@dataclass(frozen=True, slots=True)
class Option:
    id: str
    label: str


@dataclass(frozen=True, slots=True)
class Requirement:
    key: str
    prompt: str
    kind: InputKind
    options: tuple[Option, ...] = ()

    def __post_init__(self) -> None:
        if not self.key or not self.prompt:
            raise ValueError("Requirements need a key and prompt")
        if self.kind in (InputKind.SINGLE_SELECT, InputKind.MULTI_SELECT):
            ids = [option.id for option in self.options]
            if not ids or len(ids) != len(set(ids)) or any(not id for id in ids):
                raise ValueError("Selection requires unique, nonempty option IDs")
        elif self.options:
            raise ValueError("URL requirement cannot have options")


@dataclass(frozen=True, slots=True)
class GuidanceDefinition:
    objective: str
    requirements: tuple[Requirement, ...]

    def __post_init__(self) -> None:
        keys = [requirement.key for requirement in self.requirements]
        if not self.objective or len(keys) != len(set(keys)):
            raise ValueError("Objective and unique requirement keys are required")


@dataclass(frozen=True, slots=True)
class Interaction:
    kind: InputKind
    key: str
    options: tuple[Option, ...] = ()


@dataclass(frozen=True, slots=True)
class GuidanceResponse:
    message: str
    status: str
    interaction: Interaction | None = None
    resolved: dict[str, str | tuple[str, ...]] = field(default_factory=dict)


class GuidanceSession:
    """Collects explicit target information; never performs product actions."""

    def __init__(self, definition: GuidanceDefinition) -> None:
        self.definition = definition
        self._answers: dict[str, str | tuple[str, ...]] = {}

    def current(self) -> GuidanceResponse:
        for requirement in self.definition.requirements:
            if requirement.key not in self._answers:
                return GuidanceResponse(
                    message=requirement.prompt,
                    status="needs_input",
                    interaction=Interaction(
                        kind=requirement.kind,
                        key=requirement.key,
                        options=requirement.options,
                    ),
                    resolved=self._answers.copy(),
                )
        return GuidanceResponse(
            message="Your target is identified. Follow the product's guidance to continue.",
            status="ready_for_guidance",
            resolved=self._answers.copy(),
        )

    def submit(self, key: str, value: str | list[str] | tuple[str, ...]) -> GuidanceResponse:
        """Accept answers only for the current requirement, in order."""
        pending = self.current().interaction
        if pending is None:
            raise ValueError("All requested information has already been supplied")
        if key != pending.key:
            raise ValueError("Answer does not match the requested input")
        requirement = next(item for item in self.definition.requirements if item.key == key)
        self._answers[key] = self._validate(requirement, value)
        return self.current()

    @staticmethod
    def _validate(requirement: Requirement, value: str | list[str] | tuple[str, ...]) -> str | tuple[str, ...]:
        if requirement.kind == InputKind.URL:
            if not isinstance(value, str):
                raise ValueError("A URL must be a string")
            value = value.strip()
            parsed = urlsplit(value)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Enter an absolute http(s) URL without credentials")
            return value

        allowed = {option.id for option in requirement.options}
        if requirement.kind == InputKind.SINGLE_SELECT:
            if not isinstance(value, str) or value not in allowed:
                raise ValueError("Select one of the provided option IDs")
            return value

        if not isinstance(value, (list, tuple)) or not value:
            raise ValueError("Select at least one option")
        if any(not isinstance(item, str) or item not in allowed for item in value):
            raise ValueError("Unknown option ID")
        if len(value) != len(set(value)):
            raise ValueError("Duplicate selections are not allowed")
        return tuple(value)

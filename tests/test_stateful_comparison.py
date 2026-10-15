import pytest

from purrfect.guidance import GuidanceDefinition, InputKind, Option, Requirement
from purrfect.stateful import Turn
from purrfect.stateful_custom import CustomConversation
from purrfect.stateful_langgraph import LangGraphConversation


@pytest.fixture(params=[CustomConversation, LangGraphConversation], ids=["custom", "langgraph"])
def engine(request):
    definition = GuidanceDefinition(
        "Guide post translation",
        (
            Requirement("post_url", "Which post?", InputKind.URL),
            Requirement("section", "Which section?", InputKind.SINGLE_SELECT,
                        (Option("hero", "Hero"), Option("body", "Body"))),
        ),
    )
    return request.param(definition)


def test_multiple_turns_and_corrections(engine):
    assert engine.send("a", Turn("start")).interaction.key == "post_url"
    assert engine.send("a", Turn("answer", "post_url", "https://example.org/1")).interaction.key == "section"
    assert engine.send("a", Turn("answer", "section", "hero")).status == "ready_for_guidance"
    changed = engine.send("a", Turn("correct", "post_url", "https://example.org/2"))
    assert changed.interaction.key == "section"
    assert changed.resolved == {"post_url": "https://example.org/2"}
    assert engine.send("a", Turn("answer", "section", "body")).resolved["section"] == "body"


def test_separate_sessions(engine):
    engine.send("a", Turn("start"))
    engine.send("a", Turn("answer", "post_url", "https://example.org/a"))
    assert engine.send("b", Turn("start")).interaction.key == "post_url"
    assert engine.send("b", Turn("answer", "post_url", "https://example.org/b")).resolved["post_url"] == "https://example.org/b"


def test_invalid_input_preserves_state(engine):
    engine.send("a", Turn("start"))
    with pytest.raises(ValueError):
        engine.send("a", Turn("answer", "post_url", "not-a-url"))
    assert engine.send("a", Turn("answer", "post_url", "https://example.org")).interaction.key == "section"
    with pytest.raises(ValueError):
        engine.send("a", Turn("answer", "section", "unknown"))
    assert engine.send("a", Turn("answer", "section", "hero")).status == "ready_for_guidance"


def test_wrong_target_cannot_advance(engine):
    engine.send("a", Turn("start"))
    with pytest.raises(ValueError):
        engine.send("a", Turn("answer", "section", "hero"))
    assert engine.send("a", Turn("answer", "post_url", "https://example.org")).interaction.key == "section"

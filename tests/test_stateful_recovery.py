"""Identical disk-restart and pause/resume scenarios for both implementations."""

import pytest

from purrfect.guidance import GuidanceDefinition, InputKind, Option, Requirement
from purrfect.stateful import Turn
from purrfect.stateful_custom import CustomConversation
from purrfect.stateful_langgraph import LangGraphConversation


@pytest.fixture(params=[CustomConversation, LangGraphConversation], ids=["custom", "langgraph"])
def engine_type(request):
    return request.param


@pytest.fixture
def definition():
    return GuidanceDefinition(
        "Guide translation",
        (
            Requirement("post_url", "Which post?", InputKind.URL),
            Requirement(
                "section", "Which section?", InputKind.SINGLE_SELECT,
                (Option("hero", "Hero"), Option("body", "Body")),
            ),
        ),
    )


def test_resume_after_process_restart(tmp_path, definition, engine_type):
    path = tmp_path / "sessions.sqlite"
    first = engine_type(definition, path)
    assert first.send("child-A", Turn("start")).interaction.key == "post_url"
    assert first.send(
        "child-A", Turn("answer", "post_url", "https://example.org/post")
    ).interaction.key == "section"
    if hasattr(first, "close"):
        first.close()

    # Different object, backed by the same on-disk database.
    resumed = engine_type(definition, path)
    response = resumed.send("child-A", Turn("answer", "section", "hero"))
    assert response.status == "ready_for_guidance"
    assert response.resolved == {
        "post_url": "https://example.org/post", "section": "hero"
    }
    if hasattr(resumed, "close"):
        resumed.close()


def test_correction_after_restart_invalidates_stale_section(
    tmp_path, definition, engine_type
):
    path = tmp_path / "sessions.sqlite"
    first = engine_type(definition, path)
    first.send("child-A", Turn("start"))
    first.send("child-A", Turn("answer", "post_url", "https://example.org/old"))
    first.send("child-A", Turn("answer", "section", "hero"))
    if hasattr(first, "close"):
        first.close()

    resumed = engine_type(definition, path)
    changed = resumed.send(
        "child-A", Turn("correct", "post_url", "https://example.org/new")
    )
    assert changed.status == "needs_input"
    assert changed.interaction.key == "section"
    assert changed.resolved == {"post_url": "https://example.org/new"}
    assert resumed.send(
        "child-A", Turn("answer", "section", "body")
    ).status == "ready_for_guidance"
    if hasattr(resumed, "close"):
        resumed.close()


def test_restart_preserves_isolation_and_rejects_invalid_answer(
    tmp_path, definition, engine_type
):
    path = tmp_path / "sessions.sqlite"
    first = engine_type(definition, path)
    first.send("child-A", Turn("start"))
    first.send("child-A", Turn("answer", "post_url", "https://example.org/a"))
    first.send("child-B", Turn("start"))
    if hasattr(first, "close"):
        first.close()

    resumed = engine_type(definition, path)
    with pytest.raises(ValueError):
        resumed.send("child-B", Turn("answer", "section", "hero"))
    assert resumed.send(
        "child-B", Turn("answer", "post_url", "https://example.org/b")
    ).interaction.key == "section"
    assert resumed.send(
        "child-A", Turn("answer", "section", "hero")
    ).resolved["post_url"] == "https://example.org/a"
    if hasattr(resumed, "close"):
        resumed.close()

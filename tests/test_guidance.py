import pytest

from purrfect.guidance import (
    GuidanceDefinition,
    GuidanceSession,
    InputKind,
    Option,
    Requirement,
)


@pytest.fixture
def session():
    # Fixture represents product-provided knowledge/targets, not invented RAG results.
    definition = GuidanceDefinition(
        objective="Guide user to translate post sections",
        requirements=(
            Requirement("post_url", "Which post? Paste its URL.", InputKind.URL),
            Requirement(
                "sections", "Which sections need translation?", InputKind.MULTI_SELECT,
                (Option("section-1", "Hero"), Option("section-2", "Body")),
            ),
        ),
    )
    return GuidanceSession(definition)


def test_guidance_collects_url_then_stable_section_ids(session):
    response = session.current()
    assert response.status == "needs_input"
    assert response.interaction.key == "post_url"
    response = session.submit("post_url", " https://example.com/post/ ")
    assert response.interaction.key == "sections"
    assert response.interaction.options[0].id == "section-1"
    response = session.submit("sections", ["section-2", "section-1"])
    assert response.status == "ready_for_guidance"
    assert response.interaction is None
    assert response.resolved == {
        "post_url": "https://example.com/post/",
        "sections": ("section-2", "section-1"),
    }


@pytest.mark.parametrize("url", [
    "", "not-a-url", "file:///etc/passwd", "https://", "https://user:pass@example.com",
])
def test_invalid_urls_cannot_advance(session, url):
    with pytest.raises(ValueError):
        session.submit("post_url", url)
    assert session.current().interaction.key == "post_url"


def test_missing_and_unknown_targets_cannot_advance(session):
    with pytest.raises(ValueError):
        session.submit("sections", ["section-1"])
    session.submit("post_url", "https://example.com/post")
    for selection in ([], ["missing"], ["section-1", "section-1"], "section-1"):
        with pytest.raises(ValueError):
            session.submit("sections", selection)
    assert session.current().interaction.key == "sections"


def test_single_selection_and_completion():
    session = GuidanceSession(GuidanceDefinition(
        "Choose section",
        (Requirement("section", "Which one?", InputKind.SINGLE_SELECT,
                     (Option("a", "Intro"), Option("b", "Footer"))),),
    ))
    with pytest.raises(ValueError):
        session.submit("section", "Intro")
    assert session.submit("section", "a").resolved == {"section": "a"}
    with pytest.raises(ValueError):
        session.submit("section", "b")


def test_definition_rejects_ambiguous_option_ids():
    with pytest.raises(ValueError):
        Requirement("target", "Choose", InputKind.SINGLE_SELECT,
                    (Option("same", "One"), Option("same", "Two")))


def test_exposed_answers_are_not_mutable_session_state(session):
    state = session.current()
    state.resolved["post_url"] = "untrusted"
    assert session.current().resolved == {}

import json

import pytest

from purrfect.adaptive import AdaptiveGuide
from purrfect.brain import ProductObjective
from purrfect.guidance import GuidanceDefinition, InputKind, Option, Requirement
from purrfect.stateful_custom import CustomConversation
from purrfect.stateful_langgraph import LangGraphConversation


class ScriptedModel:
    def __init__(self, *replies):
        self.replies = iter(replies)
        self.inputs = []

    async def complete(self, system, user):
        self.inputs.append(json.loads(user))
        return next(self.replies)


@pytest.fixture
def objectives():
    post = Requirement("post_url", "Which post?", InputKind.URL)
    section = Requirement("section", "Which section?", InputKind.SINGLE_SELECT,
                          (Option("hero", "Hero"), Option("body", "Body")))
    return (
        ProductObjective("translate", GuidanceDefinition("Translate post", (post, section))),
        ProductObjective("missing_button", GuidanceDefinition(
            "Troubleshoot a missing translate button", (post,),
        )),
        ProductObjective("settings", GuidanceDefinition(
            "Explain product settings", (Requirement(
                "topic", "Which topic?", InputKind.SINGLE_SELECT,
                (Option("language", "Language"), Option("layout", "Layout"))
            ),),
        )),
    )


@pytest.fixture(params=[CustomConversation, LangGraphConversation], ids=["custom", "langgraph"])
def backend(request):
    return request.param


@pytest.mark.asyncio
async def test_continue_and_correct_preserve_context(objectives, backend):
    model = ScriptedModel(
        '{"objective_id":"translate"}',
        '{"kind":"continue","key":"post_url","value":"https://example.org/post"}',
        '{"kind":"continue","key":"section","value":"hero"}',
        '{"kind":"correct","key":"post_url","value":"https://example.org/new"}',
    )
    guide = AdaptiveGuide(model, objectives, backend)
    assert (await guide.start("client-A", "Please translate")).interaction.key == "post_url"
    assert (await guide.message("client-A", "This post")).interaction.key == "section"
    assert (await guide.message("client-A", "Hero")).status == "ready_for_guidance"
    corrected = await guide.message("client-A", "Actually this post instead")
    assert corrected.interaction.key == "section"
    assert corrected.resolved == {"post_url": "https://example.org/new"}


@pytest.mark.asyncio
async def test_switch_preserves_valid_shared_target(objectives, backend):
    guide = AdaptiveGuide(ScriptedModel(
        '{"objective_id":"translate"}',
        '{"kind":"continue","key":"post_url","value":"https://example.org/post"}',
        '{"kind":"switch","objective_id":"missing_button"}',
    ), objectives, backend)
    await guide.start("client-A", "Translate")
    await guide.message("client-A", "Post URL")
    switched = await guide.message("client-A", "Actually the button is missing")
    assert switched.status == "ready_for_guidance"
    assert switched.resolved == {"post_url": "https://example.org/post"}
    assert guide.current["client-A"] == "missing_button"


@pytest.mark.asyncio
async def test_switch_does_not_transfer_unrelated_answers(objectives, backend):
    guide = AdaptiveGuide(ScriptedModel(
        '{"objective_id":"translate"}',
        '{"kind":"continue","key":"post_url","value":"https://example.org/post"}',
        '{"kind":"switch","objective_id":"settings"}',
    ), objectives, backend)
    await guide.start("a", "Translate")
    await guide.message("a", "Post URL")
    response = await guide.message("a", "I want settings help")
    assert response.resolved == {}
    assert response.interaction.key == "topic"


@pytest.mark.asyncio
async def test_ambiguous_or_unsafe_routes_do_not_change_state(objectives, backend):
    guide = AdaptiveGuide(ScriptedModel(
        '{"objective_id":"translate"}',
        '{"kind":"continue","key":"section","value":"hero"}',
        '{"kind":"continue","key":"post_url","value":"javascript:bad"}',
        '{"kind":"switch","objective_id":"invented"}',
        '{"kind":"clarify"}',
        '{"kind":"continue","key":"post_url","value":"https://example.org/good"}',
    ), objectives, backend)
    await guide.start("a", "Translate")
    for _ in range(4):
        assert (await guide.message("a", "not sure")).status == "clarification"
    assert (await guide.message("a", "Here")).interaction.key == "section"


@pytest.mark.asyncio
async def test_unsupported_objective_fails_closed(objectives, backend):
    guide = AdaptiveGuide(ScriptedModel('{"objective_id":"invented"}'), objectives, backend)
    assert (await guide.start("a", "Do something")).status == "clarification"
    assert "a" not in guide.current


@pytest.mark.asyncio
async def test_separate_clients(objectives, backend):
    guide = AdaptiveGuide(ScriptedModel(
        '{"objective_id":"translate"}', '{"objective_id":"settings"}'
    ), objectives, backend)
    assert (await guide.start("a", "Translate")).interaction.key == "post_url"
    assert (await guide.start("b", "Settings")).interaction.key == "topic"
    assert guide.current == {"a": "translate", "b": "settings"}

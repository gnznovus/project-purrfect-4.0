import json

import pytest

from purrfect.brain import ProductObjective, PurraBrain
from purrfect.guidance import GuidanceDefinition, InputKind, Option, Requirement


class FakeModel:
    def __init__(self, output):
        self.output = output
        self.calls = []

    async def complete(self, system, user):
        self.calls.append((system, json.loads(user)))
        return self.output


@pytest.fixture
def objectives():
    return (
        ProductObjective("translate", GuidanceDefinition(
            "Help user translate a post",
            (
                Requirement("post_url", "Paste the post URL.", InputKind.URL),
                Requirement("section", "Select a section.", InputKind.SINGLE_SELECT,
                            (Option("hero-123", "Hero"), Option("body-456", "Body"))),
            ),
        )),
        ProductObjective("help", GuidanceDefinition(
            "Explain how to use product settings",
            (),
        )),
    )


@pytest.mark.asyncio
async def test_selects_product_objective_and_collects_real_targets(objectives):
    model = FakeModel('{"objective_id":"translate"}')
    result = await PurraBrain(model).start("Translate this post", objectives)
    assert result.response.status == "needs_input"
    assert result.response.interaction.key == "post_url"
    assert result.session is not None
    result.session.submit("post_url", "https://example.org/post/1")
    next_response = result.session.current()
    assert [o.id for o in next_response.interaction.options] == [
        "hero-123", "body-456",
    ]
    ready = result.session.submit("section", "hero-123")
    assert ready.status == "ready_for_guidance"
    assert ready.resolved["section"] == "hero-123"
    assert model.calls[0][1]["available_objectives"][0]["id"] == "translate"


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [
    "not json", "[]", "{}", '{"objective_id":"delete_database"}',
    '{"objective_id":null}', '{"objective_id":"translate","command":"rm -rf /"}',
    '{"objective_id":123}',
])
async def test_untrusted_model_output_fails_closed(reply, objectives):
    result = await PurraBrain(FakeModel(reply)).start("Do something", objectives)
    assert result.response.status == "unsupported"
    assert result.session is None


@pytest.mark.asyncio
async def test_empty_catalog_fails_closed():
    result = await PurraBrain(FakeModel("unavailable")).start("Help", ())
    assert result.response.status == "unsupported"


@pytest.mark.asyncio
async def test_does_not_call_model_on_empty_request(objectives):
    model = FakeModel('{"objective_id":"translate"}')
    with pytest.raises(ValueError):
        await PurraBrain(model).start("   ", objectives)
    assert not model.calls


@pytest.mark.asyncio
async def test_ready_response_does_not_execute_anything(objectives):
    result = await PurraBrain(FakeModel('{"objective_id":"help"}')).start(
        "Explain settings", objectives
    )
    assert result.response.status == "ready_for_guidance"
    assert result.response.interaction is None

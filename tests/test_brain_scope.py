import json

import pytest

from purrfect.brain_scope import select_scope
from purrfect.discovery import discover
from purrfect.knowledge import EVERYDAY_WORDPRESS, SiteKnowledge


class Model:
    def __init__(self, reply):
        self.reply = reply
        self.context = None

    async def complete(self, system, user):
        self.context = json.loads(user)
        return self.reply


def catalog():
    snapshot = {
        "active": [{"kind": "plugin", "key": "mock/main.php"}],
        "signals": [{
            "kind": "plugin", "key": "mock/main.php",
            "product_id": "mock-translation", "version": "1",
            "contract": 1, "capabilities": ["translate-content"],
            "knowledge": [{
                "id": "edit", "title": "Translate content",
                "text": "Open mock translations.",
                "source": "mock://docs", "tags": ["translate", "content"],
            }],
        }],
    }
    return SiteKnowledge(discover(snapshot).products, EVERYDAY_WORDPRESS)


@pytest.mark.asyncio
@pytest.mark.parametrize(("raw", "expected"), [
    ('{"selection":"mock-translation"}', "mock-translation"),
    ('{"selection":"wordpress"}', "wordpress"),
    ('{"selection":"other"}', "other"),
    ('{"selection":null}', None),
    ('{"selection":"invented"}', None),
    ('{"selection":"mock-translation","answer":"delete data"}', None),
    ('not-json', None),
])
async def test_only_supported_scopes_are_allowed(raw, expected):
    model = Model(raw)
    assert await select_scope(model, "Translate this", catalog()) == expected
    assert model.context["registered_products"][0]["id"] == "mock-translation"


@pytest.mark.asyncio
async def test_inactive_product_never_advertised():
    model = Model('{"selection":"mock-translation"}')
    knowledge = SiteKnowledge((), EVERYDAY_WORDPRESS)
    assert await select_scope(model, "Translate", knowledge) is None
    assert model.context["registered_products"] == []

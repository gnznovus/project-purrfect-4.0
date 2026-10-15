import json

import pytest

from purrfect.discovery import discover
from purrfect.knowledge import Evidence, EVERYDAY_WORDPRESS, SiteKnowledge
from purrfect.scope import ScopeGuide


def inventory():
    return {
        "active": [
            {"kind": "plugin", "key": "layout/main.php"},
            {"kind": "theme", "key": "site-child"},
        ],
        "signals": [
            {
                "kind": "plugin", "key": "layout/main.php",
                "product_id": "layout", "version": "1.0", "contract": 1,
                "capabilities": ["edit-template"],
                "knowledge": [{
                    "id": "edit", "title": "Edit template layout",
                    "text": "Use the layout editor to edit templates.",
                    "source": "layout://manual/edit",
                    "tags": ["layout", "template", "edit"],
                }],
            },
            {
                "kind": "theme", "key": "site-child", "product_id": "theme",
                "version": "2.0", "contract": 1, "capabilities": ["theme-settings"],
                "knowledge": [{
                    "id": "theme", "title": "Theme settings",
                    "text": "Open the theme settings panel.",
                    "source": "theme://docs/settings", "tags": ["theme", "settings"],
                }],
            },
        ],
    }


def test_multi_product_discovery_and_scoped_search():
    products = discover(inventory()).products
    assert len(products) == 2
    knowledge = SiteKnowledge(products, EVERYDAY_WORDPRESS)
    assert [item.product_id for item in knowledge.search("edit template layout", product_ids=("layout",))] == ["layout"]
    assert knowledge.search("theme settings", product_ids=("layout",)) == ()
    assert knowledge.search("edit page", general_wp=True)
    assert knowledge.search("edit page") == ()


def test_deactivation_invalidates_knowledge():
    snapshot = inventory()
    knowledge = SiteKnowledge(discover(snapshot).products)
    snapshot["active"] = [x for x in snapshot["active"] if x["key"] != "layout/main.php"]
    refreshed = discover(snapshot)
    assert len(refreshed.products) == 1
    knowledge.replace_products(refreshed.products)
    assert knowledge.search("template", product_ids=("layout",)) == ()
    assert "layout" not in knowledge.products


def test_rejects_false_activation_and_bad_contract():
    snapshot = inventory()
    snapshot["signals"].append({
        **snapshot["signals"][0], "key": "inactive/plugin.php",
        "product_id": "rogue",
    })
    snapshot["signals"].append({
        **snapshot["signals"][0], "contract": 99, "product_id": "incompatible",
    })
    result = discover(snapshot)
    assert len(result.products) == 2
    assert len(result.rejected) == 2


def test_version_and_source_isolation():
    snapshot = inventory()
    snapshot["signals"][0]["knowledge"][0]["source"] = ""
    assert "layout" not in [p.id for p in discover(snapshot).products]
    snapshot = inventory()
    snapshot["signals"][0]["version"] = "2.0"
    product = discover(snapshot).products[0]
    assert product.evidence[0].version == "2.0"


class FakeModel:
    def __init__(self, value):
        self.value = value

    async def complete(self, system, user):
        return json.dumps(self.value)


@pytest.mark.asyncio
async def test_product_scope_returns_source_evidence():
    knowledge = SiteKnowledge(discover(inventory()).products, EVERYDAY_WORDPRESS)
    guide = ScopeGuide(FakeModel({"scope": "product", "product_ids": ["layout"]}), knowledge)
    result = await guide.answer("How do I edit the layout template?")
    assert result.scope == "product"
    assert result.response.status == "grounded"
    assert result.evidence[0].source == "layout://manual/edit"


@pytest.mark.asyncio
async def test_everyday_wp_scope_and_clarification():
    knowledge = SiteKnowledge(discover(inventory()).products, EVERYDAY_WORDPRESS)
    everyday = ScopeGuide(FakeModel({"scope": "wordpress", "product_ids": []}), knowledge)
    assert (await everyday.answer("How do I edit a page?")).response.status == "grounded"
    uncertain = ScopeGuide(FakeModel({"scope": "clarify", "product_ids": []}), knowledge)
    response = (await uncertain.answer("I can't edit my page")).response
    assert response.status == "needs_input"
    assert {x.id for x in response.interaction.options} == {"layout", "theme", "wordpress", "other"}


@pytest.mark.asyncio
async def test_unsupported_and_fabricated_product_fail_closed():
    knowledge = SiteKnowledge(discover(inventory()).products, EVERYDAY_WORDPRESS)
    fake = ScopeGuide(FakeModel({"scope": "product", "product_ids": ["not-installed"]}), knowledge)
    assert (await fake.answer("Magic button")).response.status == "needs_input"
    unsupported = ScopeGuide(FakeModel({"scope": "unsupported", "product_ids": []}), knowledge)
    assert (await unsupported.answer("Server hardware issue")).response.status == "unsupported"


@pytest.mark.asyncio
async def test_no_match_cannot_fabricate_answer():
    knowledge = SiteKnowledge(discover(inventory()).products, EVERYDAY_WORDPRESS)
    guide = ScopeGuide(FakeModel({"scope": "product", "product_ids": ["layout"]}), knowledge)
    response = await guide.answer("unicorn rainbow laser")
    assert response.response.status == "clarification"
    assert not response.evidence

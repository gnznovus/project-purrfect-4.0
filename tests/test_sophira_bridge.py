import json

from purrfect.knowledge import Evidence, RegisteredProduct, SiteKnowledge
from purrfect.sophira import KnowledgeItem, KnowledgePackage, SophiraCatalog, LocalSophiraClient
from purrfect.sophira_bridge import effective_knowledge, sync_request
from purrfect.sophira_storage import encode


def base():
    product = RegisteredProduct(
        "mock-translation", "1", "plugin", ("translation",),
        (Evidence("a", "Original guide", "bundled fallback", "mock://base", "mock-translation", "1"),)
    )
    return SiteKnowledge((product,))


def pkg(rev, *items):
    return KnowledgePackage("mock-translation", "1", rev, items)


def test_live_lease_overlay_fallback_and_delta():
    catalog = SophiraCatalog()
    first = pkg(1, KnowledgeItem("a", "approved first", "mock://shared"),
                KnowledgeItem("b", "additional approved answer", "mock://b"))
    catalog.publish_approved(first, approved=True)
    client = LocalSophiraClient(catalog)
    response = sync_request(client, {"products": [{"id": "mock-translation", "version": "1", "revision": None}]})
    assert response["updates"][0]["type"] == "snapshot"
    raw = response["updates"][0]["payload"]
    assert effective_knowledge(base(), [raw]).products["mock-translation"].evidence[0].text == "approved first"
    assert base().products["mock-translation"].evidence[0].text == "bundled fallback"
    second = pkg(2, KnowledgeItem("b", "revised", "mock://b"))
    catalog.publish_approved(second, approved=True)
    changed = sync_request(client, {"products": [{"id": "mock-translation", "version": "1", "revision": 1}]})
    delta = changed["updates"][0]
    assert delta["type"] == "delta"
    assert delta["removed_ids"] == ["a"]
    assert [i["id"] for i in delta["upserts"]] == ["b"]
    assert not sync_request(client, {"products": [{"id": "mock-translation", "version": "1", "revision": 2}]})["updates"]
    assert effective_knowledge(base(), [json.loads(encode(second))]).products["mock-translation"].evidence[0].text == "bundled fallback"


def test_invalid_or_incompatible_lease_ignored():
    good = pkg(1, KnowledgeItem("a", "approved", "mock://shared"))
    raw = json.loads(encode(good))
    raw["items"][0]["content"] = "tampered"
    assert effective_knowledge(base(), [raw]).products["mock-translation"].evidence[0].text == "bundled fallback"
    raw = json.loads(encode(good))
    raw["product_version"] = "2"
    assert effective_knowledge(base(), [raw]).products["mock-translation"].evidence[0].text == "bundled fallback"


def test_development_outage_switch_is_opt_in_and_only_a_marker(monkeypatch, tmp_path):
    from purrfect.local_api import _sophira_fault_active
    monkeypatch.delenv("SOPHIRA_DEV_FAULT_FILE", raising=False)
    assert _sophira_fault_active() is False
    marker = tmp_path / "sophira-offline"
    monkeypatch.setenv("SOPHIRA_DEV_FAULT_FILE", str(marker))
    assert _sophira_fault_active() is False
    marker.touch()
    assert _sophira_fault_active() is True
    marker.unlink()
    assert _sophira_fault_active() is False

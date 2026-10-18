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


def test_individual_entry_revisions_and_change_notes_are_source_bound():
    from purrfect.sophira_storage import decode
    from purrfect.sophira_bridge import versioned_source
    catalog = SophiraCatalog()
    first = pkg(1, KnowledgeItem("a", "original", "mock-translation://docs/troubleshoot/access",
                                 1, "Initial approved entry"),
                KnowledgeItem("b", "unchanged", "mock-translation://docs/other", 1,
                              "Initial approved entry"))
    catalog.publish_approved(first, approved=True)
    second = pkg(2, KnowledgeItem("a", "revised", "mock-translation://docs/troubleshoot/access",
                                  2, "Clarified admin session requirement"),
                 first.items[1])
    catalog.publish_approved(second, approved=True)
    assert versioned_source(second.items[0].source, "1.0.0", second.items[0].entry_revision) == (
        "mock-translation-1.0.0://docs/troubleshoot/access-r2"
    )
    assert versioned_source(second.items[1].source, "1.0.0", second.items[1].entry_revision) == (
        "mock-translation-1.0.0://docs/other-r1"
    )
    assert decode(encode(second)) == second
    assert effective_knowledge(base(), [json.loads(encode(second))]).products["mock-translation"].evidence[0].source == (
        "mock-translation-1://docs/troubleshoot/access-r2"
    )
    response = sync_request(LocalSophiraClient(catalog), {
        "products": [{"id": "mock-translation", "version": "1", "revision": 1}]
    })
    assert response["updates"][0]["upserts"][0]["entry_revision"] == 2
    assert response["updates"][0]["upserts"][0]["change_note"] == "Clarified admin session requirement"


def test_change_note_required_and_individual_revision_cannot_skip():
    import pytest
    catalog = SophiraCatalog()
    first = pkg(1, KnowledgeItem("a", "old", "mock://a", 1, "Created"))
    catalog.publish_approved(first, approved=True)
    with pytest.raises(ValueError, match="change note"):
        catalog.publish_approved(pkg(2, KnowledgeItem("a", "new", "mock://a", 2)), approved=True)
    with pytest.raises(ValueError, match="increment"):
        catalog.publish_approved(pkg(2, KnowledgeItem("a", "new", "mock://a", 3, "changed")), approved=True)
    with pytest.raises(ValueError, match="Unchanged"):
        catalog.publish_approved(pkg(2, KnowledgeItem("a", "old", "mock://a", 2, "not changed")), approved=True)
    assert catalog.latest("mock-translation", "1") == 1


def test_legacy_lease_checksum_remains_unchanged():
    from purrfect.sophira_storage import decode
    old = pkg(1, KnowledgeItem("a", "legacy", "mock://a"))
    encoded = encode(old)
    assert '"entry_revision"' not in encoded
    assert decode(encoded).digest == old.digest


def test_revision_four_fixture_generates_correct_sources_without_mutating_origin():
    from pathlib import Path
    from purrfect.sophira_storage import decode
    fixture = Path(__file__).parent / "fixtures" / "sophira-mock-rev4.json"
    package = decode(fixture.read_text())
    product = RegisteredProduct(
        "mock-translation", "1.0.0", "plugin", ("translation",),
        (Evidence("translation-edit", "Edit", "bundled", "mock-translation://docs/edit",
                  "mock-translation", "1.0.0"),
         Evidence("translation-troubleshoot-access", "Access", "bundled",
                  "mock-translation://docs/troubleshoot/access", "mock-translation", "1.0.0")),
    )
    overridden = effective_knowledge(SiteKnowledge((product,)), [json.loads(encode(package))])
    sources = {e.id: e.source for e in overridden.products["mock-translation"].evidence}
    assert sources == {
        "translation-edit": "mock-translation-1.0.0://docs/edit-r2",
        "translation-troubleshoot-access":
            "mock-translation-1.0.0://docs/troubleshoot/access-r2",
    }
    assert package.items[1].source == "mock-translation://docs/troubleshoot/access"

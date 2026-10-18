import pytest
from uuid import uuid7

from purrfect.sophira import (
    KnowledgeCache, KnowledgeDelta, KnowledgeItem, KnowledgePackage,
    LocalSophiraClient, SophiraCatalog, apply_delta, diff,
)
from purrfect.issue_record import build_issue_record
from purrfect.troubleshooting import start, advance
from purrfect.discovery import discover
from purrfect.knowledge import SiteKnowledge


def item(id, text):
    return KnowledgeItem(id, text, "mock://" + id)


def package(rev, *items, version="1"):
    return KnowledgePackage("mock-translation", version, rev, items)


def test_approved_distribution_and_incremental_lease():
    service = SophiraCatalog()
    client = LocalSophiraClient(service)
    cache = KnowledgeCache("mock-translation", "1")
    fallback = (item("base", "bundled"),)
    assert cache.effective(fallback) == fallback
    assert cache.refresh(client) is False
    first = package(1, item("a", "one"), item("b", "two"))
    with pytest.raises(PermissionError):
        service.publish_approved(first)
    service.publish_approved(first, approved=True)
    assert cache.refresh(client)
    assert cache.current.revision == 1
    second = package(2, item("a", "updated"), item("c", "new"))
    service.publish_approved(second, approved=True)
    delta = client.lease("mock-translation", "1", 1)
    assert isinstance(delta, KnowledgeDelta)
    assert [i.id for i in delta.upserts] == ["a", "c"]
    assert delta.removed_ids == ("b",)
    assert cache.refresh(client)
    assert cache.current.digest == second.digest
    assert cache.effective(fallback) == second.items
    assert cache.refresh(client) is False


def test_checksum_failure_preserves_last_good_and_recovery():
    service = SophiraCatalog()
    client = LocalSophiraClient(service)
    cache = KnowledgeCache("mock-translation", "1")
    service.publish_approved(package(1, item("a", "one")), approved=True)
    assert cache.refresh(client)
    good = cache.current
    service.publish_approved(package(2, item("a", "two")), approved=True)

    class Broken:
        def lease(self, *args):
            d = client.lease(*args)
            return KnowledgeDelta(d.product_id, d.product_version, d.from_revision,
                                  d.to_revision, d.upserts, d.removed_ids, "0" * 64)

    assert cache.refresh(Broken()) is False
    assert cache.current == good
    assert cache.refresh(client) is True
    assert cache.current.revision == 2


def test_network_outage_keeps_cached_or_bundled_knowledge():
    class Offline:
        def lease(self, *args):
            raise ConnectionError("sleeping cat")
    fallback = (item("base", "safe"),)
    cache = KnowledgeCache("mock-translation", "1")
    assert cache.refresh(Offline()) is False
    assert cache.effective(fallback) == fallback
    service = SophiraCatalog()
    service.publish_approved(package(1, item("a", "leased")), approved=True)
    assert cache.refresh(LocalSophiraClient(service))
    assert cache.refresh(Offline()) is False
    assert cache.effective(fallback) == (item("a", "leased"),)


def test_reject_incompatible_or_out_of_order_revisions():
    first = package(1, item("a", "one"))
    wrong = package(2, item("a", "two"), version="2")
    with pytest.raises(ValueError):
        diff(first, wrong)
    with pytest.raises(ValueError):
        apply_delta(first, diff(first, package(2, item("a", "two"))).__class__(
            "mock-translation", "1", 2, 3, (), (), "0" * 64
        ))
    service = SophiraCatalog()
    service.publish_approved(first, approved=True)
    with pytest.raises(ValueError):
        service.publish_approved(package(3, item("a", "three")), approved=True)


def test_issue_record_uses_validated_attempts_and_requires_terminal_state():
    snapshot = {
        "active": [{"kind": "plugin", "key": "mock/file.php"}],
        "signals": [{
            "kind": "plugin", "key": "mock/file.php", "product_id": "mock-translation",
            "version": "1", "contract": 1, "capabilities": ["translation"],
            "knowledge": [{"id": "e", "title": "check", "text": "Verify plugin",
                           "source": "mock://source", "tags": []}],
            "troubleshooting": [{"id": "p", "title": "Missing panel",
                "steps": [{"id": "s", "instruction": "Check plugin", "evidence_id": "e"}]}],
        }],
    }
    knowledge = SiteKnowledge(discover(snapshot).products)
    state, _ = start(knowledge, "mock-translation", "p")
    with pytest.raises(ValueError):
        build_issue_record(knowledge, state, str(uuid7()), "Panel missing")
    state, _ = advance(knowledge, state, "failed")
    record = build_issue_record(knowledge, state, str(uuid7()), "Panel missing")
    assert record.export()["outcome"] == "escalation_required"
    assert record.attempts[0].source == "mock://source"
    assert record.attempts[0].user_reported_result == "failed"
    with pytest.raises(ValueError):
        build_issue_record(knowledge, state, str(uuid7()), "")

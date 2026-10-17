from purrfect.sophira import KnowledgeItem, KnowledgePackage, LocalSophiraClient
from purrfect.sophira_storage import DurableSophira, SiteLeaseStore
import pytest


def pack(revision, text):
    return KnowledgePackage("mock-translation", "1", revision,
                            (KnowledgeItem("check", text, "mock://approved"),))


def test_two_sites_delta_restart_and_outage(tmp_path):
    sophira_path = tmp_path / "sophira.db"
    site_path = tmp_path / "child-cache.db"
    sophira = DurableSophira(sophira_path)
    with pytest.raises(PermissionError):
        sophira.publish_approved(pack(1, "first"))
    sophira.publish_approved(pack(1, "first"), approved=True)
    a, b = SiteLeaseStore(site_path, "site-a"), SiteLeaseStore(site_path, "site-b")
    client = LocalSophiraClient(sophira)
    assert a.refresh(client, "mock-translation", "1")
    assert b.refresh(client, "mock-translation", "1")
    sophira.publish_approved(pack(2, "approved update"), approved=True)
    assert a.refresh(client, "mock-translation", "1")
    assert a.get("mock-translation", "1").revision == 2
    assert b.get("mock-translation", "1").revision == 1
    assert b.refresh(client, "mock-translation", "1")
    assert b.get("mock-translation", "1").revision == 2
    a.close()
    b.close()
    sophira.close()
    a = SiteLeaseStore(site_path, "site-a")
    b = SiteLeaseStore(site_path, "site-b")
    assert a.get("mock-translation", "1").items[0].content == "approved update"
    assert b.get("mock-translation", "1").items[0].content == "approved update"
    sophira = DurableSophira(sophira_path)
    assert sophira.latest("mock-translation", "1") == 2
    assert not a.refresh(LocalSophiraClient(sophira), "mock-translation", "1")
    sophira.close()
    assert a.get("mock-translation", "1").revision == 2
    a.close()
    b.close()


def test_corruption_rejected_without_silent_fallback(tmp_path):
    path = tmp_path / "sophira.db"
    service = DurableSophira(path)
    service.publish_approved(pack(1, "valid"), approved=True)
    service.close()
    import sqlite3
    with sqlite3.connect(path) as db:
        db.execute("UPDATE knowledge_revisions SET payload = ?", ('{"broken":true}',))
    with pytest.raises(ValueError):
        DurableSophira(path)

def test_running_purra_observes_external_operator_publication(tmp_path):
    path = tmp_path / "sophira.db"
    running = DurableSophira(path)
    operator = DurableSophira(path)
    try:
        operator.publish_approved(pack(1, "operator approved"), approved=True)
        assert running.latest("mock-translation", "1") == 1
        assert running.lease("mock-translation", "1").items[0].content == "operator approved"
        operator.publish_approved(pack(2, "revision two"), approved=True)
        assert running.latest("mock-translation", "1") == 2
        assert running.lease("mock-translation", "1", 1).to_revision == 2
    finally:
        operator.close()
        running.close()

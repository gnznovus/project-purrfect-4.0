import pytest
from purrfect.sophira import KnowledgeItem, KnowledgePackage, KnowledgeCache, LocalSophiraClient, apply_delta, diff
from purrfect.sophira_storage import DurableSophira, encode, decode

def package(rev, content):
    return KnowledgePackage("product","1",rev,(KnowledgeItem("a",content,"manual://a"),))
def test_approved_knowledge(tmp_path):
    db=DurableSophira(tmp_path / "catalog.db")
    with pytest.raises(PermissionError):
        db.publish_approved(package(1,"a"))
    db.publish_approved(package(1,"a"),approved=True)
    cache=KnowledgeCache("product","1")
    assert cache.refresh(LocalSophiraClient(db))
    db.publish_approved(package(2,"b"),approved=True)
    assert cache.refresh(LocalSophiraClient(db))
    assert cache.current.items[0].content=="b"
    assert apply_delta(package(1,"a"),diff(package(1,"a"),package(2,"b"))).digest==package(2,"b").digest
    assert decode(encode(package(1,"a")))==package(1,"a")
    db.close()

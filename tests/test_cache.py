from purrfect.infrastructure.cache import RetrievalCache
from purrfect.sophira import KnowledgeItem, KnowledgePackage


def package(revision, text, tenant="a"):
    return KnowledgePackage(f"{tenant}/demo", "1", revision, (
        KnowledgeItem("install", text, "manual://install"),
    ))


def test_revision_change_invalidates_cache_and_tenant_isolation():
    cache = RetrievalCache(max_entries=3)
    calls = []
    def lookup(doc, query):
        calls.append((doc.product_id, doc.revision))
        return doc.items

    first = cache.lookup("a", "demo", package(1, "old"), "install", lookup)
    again = cache.lookup("a", "demo", package(1, "old"), "INSTALL", lookup)
    updated = cache.lookup("a", "demo", package(2, "new"), "install", lookup)
    other = cache.lookup("b", "demo", package(1, "private", tenant="b"), "install", lookup)
    assert first == again
    assert updated[0].content == "new" and other[0].content == "private"
    assert calls == [("a/demo", 1), ("a/demo", 2), ("b/demo", 1)]
    assert cache.size == 3


def test_lru_is_bounded():
    cache = RetrievalCache(max_entries=2)
    def retrieve(doc, query):
        return doc.items
    doc = package(1, "hello")
    for question in ("one", "two", "three"):
        cache.lookup("a", "demo", doc, question, retrieve)
    assert cache.size == 2

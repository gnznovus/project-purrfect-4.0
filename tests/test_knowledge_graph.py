"""Graph-aware product evidence remains scoped, consistent and optional."""

import pytest

from purrfect.discovery import discover
from purrfect.knowledge import Evidence, RegisteredProduct, SiteKnowledge


def product(nodes):
    return RegisteredProduct("sle", "1", "theme", (), tuple(nodes))


def graph():
    return product((
        Evidence("root", "Theme Manager", "Manage the site.", "sle://root", "sle", "1",
                 ("theme manager",), child_ids=("import", "translation")),
        Evidence("import", "Import package", "Upload the package ZIP.", "sle://import",
                 "sle", "1", ("import",), parent_id="root",
                 navigation={"target_id": "sle:import-package"}),
        Evidence("translation", "Translation provider", "Set up translation.", "sle://translation",
                 "sle", "1", ("translation",), parent_id="root",
                 navigation={"target_id": "sle:translation-provider"}),
    ))


def test_search_traverses_parent_and_keeps_product_scope():
    site = SiteKnowledge((graph(),))
    found = site.search("translation", product_ids=("sle",))
    assert [entry.id for entry in found][:2] == ["translation", "root"]
    assert site.search("translation", product_ids=()) == ()


def test_broken_backlink_and_cycle_rejected():
    with pytest.raises(ValueError, match="link mismatch"):
        product((Evidence("root", "Root", "Text", "sle://root", "sle", "1",
                          child_ids=("child",)),))
    with pytest.raises(ValueError, match="cycle"):
        product((
            Evidence("a", "A", "Text", "sle://a", "sle", "1",
                     parent_id="b", child_ids=("b",)),
            Evidence("b", "B", "Text", "sle://b", "sle", "1",
                     parent_id="a", child_ids=("a",)),
        ))


def test_discovery_accepts_graph_metadata_and_old_records():
    node = {"id": "root", "title": "Root", "text": "Root guide", "source": "sle://root",
            "tags": ["root"], "child_ids": ["child"]}
    child = {"id": "child", "title": "Import", "text": "Import guide",
             "source": "sle://import", "tags": ["import"], "parent_id": "root",
             "navigation": {"target_id": "sle:import-package"}}
    signal = {"kind": "theme", "key": "theme", "product_id": "sle", "version": "1",
              "contract": 1, "capabilities": [], "knowledge": [node, child]}
    snapshot = {"active": [{"kind": "theme", "key": "theme"}], "signals": [signal]}
    result = discover(snapshot)
    assert not result.rejected
    assert result.products[0].evidence[1].navigation == {"target_id": "sle:import-package"}
    signal["knowledge"] = [{"id": "old", "title": "Old", "text": "Legacy guide",
                            "source": "sle://old", "tags": []}]
    assert len(discover(snapshot).products) == 1


def test_discovery_rejects_dangling_links():
    node = {"id": "root", "title": "Root", "text": "Root guide", "source": "sle://root",
            "tags": [], "child_ids": ["missing"]}
    result = discover({"active": [{"kind": "theme", "key": "theme"}],
                       "signals": [{"kind": "theme", "key": "theme",
                                    "product_id": "sle", "version": "1",
                                    "contract": 1, "capabilities": [], "knowledge": [node]}]})
    assert not result.products
    assert result.rejected

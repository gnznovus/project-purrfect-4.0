"""Goal 1.8a: advertised troubleshooting procedures remain product-owned and scoped."""

from copy import deepcopy

from purrfect.discovery import discover
from purrfect.knowledge import SiteKnowledge


def inventory():
    return {
        "active": [{"kind": "plugin", "key": "mock/test.php"}],
        "signals": [{
            "kind": "plugin", "key": "mock/test.php",
            "product_id": "mock-translation", "version": "1", "contract": 1,
            "capabilities": ["translate-content"],
            "knowledge": [
                {"id": "check-plugin", "title": "Check plugin",
                 "text": "Verify the plugin is active.", "source": "mock://plugin",
                 "tags": ["plugin"]},
                {"id": "check-access", "title": "Check access",
                 "text": "Verify admin access.", "source": "mock://access",
                 "tags": ["access"]},
            ],
            "troubleshooting": [{
                "id": "panel-unavailable", "title": "Panel unavailable",
                "steps": [
                    {"id": "plugin", "instruction": "Verify active plugin.",
                     "evidence_id": "check-plugin"},
                    {"id": "access", "instruction": "Verify administrator access.",
                     "evidence_id": "check-access"},
                ],
            }],
        }],
    }


def test_multi_step_procedure_is_ordered_and_evidence_bound():
    result = discover(inventory())
    assert not result.rejected
    product = result.products[0]
    procedure = product.troubleshooting[0]
    assert procedure.id == "panel-unavailable"
    assert [s.id for s in procedure.steps] == ["plugin", "access"]
    assert [s.evidence_id for s in procedure.steps] == ["check-plugin", "check-access"]
    assert all(s.evidence_id in {e.id for e in product.evidence} for s in procedure.steps)


def test_legacy_product_signal_remains_compatible():
    snapshot = inventory()
    del snapshot["signals"][0]["troubleshooting"]
    assert discover(snapshot).products[0].troubleshooting == ()


def test_invalid_procedures_fail_closed_without_registering_product():
    variants = [
        lambda p: p["steps"][1].update(id="plugin"),
        lambda p: p["steps"][1].update(evidence_id="invented"),
        lambda p: p.update(steps=[]),
        lambda p: p["steps"][0].update(instruction=""),
        lambda p: p["steps"][0].update(unexpected="field"),
        lambda p: p.update(unknown="field"),
    ]
    for mutate in variants:
        snapshot = inventory()
        mutate(snapshot["signals"][0]["troubleshooting"][0])
        result = discover(snapshot)
        assert result.products == ()
        assert result.rejected


def test_unknown_top_level_signal_field_still_rejected():
    snapshot = inventory()
    snapshot["signals"][0]["arbitrary"] = "not allowed"
    assert not discover(snapshot).products


def test_deactivated_product_procedures_are_not_available():
    snapshot = inventory()
    knowledge = SiteKnowledge(discover(snapshot).products)
    assert knowledge.products["mock-translation"].troubleshooting
    snapshot["active"] = []
    knowledge.replace_products(discover(snapshot).products)
    assert "mock-translation" not in knowledge.products


def test_troubleshooting_contract_does_not_change_existing_search():
    snapshot = inventory()
    with_procedures = SiteKnowledge(discover(snapshot).products)
    without = deepcopy(snapshot)
    del without["signals"][0]["troubleshooting"]
    legacy = SiteKnowledge(discover(without).products)
    assert with_procedures.search("plugin", product_ids=("mock-translation",)) == legacy.search(
        "plugin", product_ids=("mock-translation",)
    )

"""Goal 1.8b: pure troubleshooting lifecycle, recovery, and safety boundaries."""
from copy import deepcopy

import pytest

from purrfect.discovery import discover
from purrfect.knowledge import SiteKnowledge
from purrfect.troubleshooting import advance, current, explain, restore, start


def inventory():
    return {
        "active": [{"kind": "plugin", "key": "mock/test.php"}],
        "signals": [{
            "kind": "plugin", "key": "mock/test.php",
            "product_id": "mock-translation", "version": "1", "contract": 1,
            "capabilities": ["translate-content"],
            "knowledge": [
                {"id": "plugin", "title": "Plugin", "text": "Check the plugin activation.",
                 "source": "mock://plugin", "tags": ["plugin"]},
                {"id": "admin", "title": "Admin", "text": "Check your admin access.",
                 "source": "mock://admin", "tags": ["admin"]},
            ],
            "troubleshooting": [{
                "id": "missing-panel", "title": "Missing panel",
                "steps": [
                    {"id": "check-plugin", "instruction": "Verify the plugin.",
                     "evidence_id": "plugin"},
                    {"id": "check-admin", "instruction": "Verify admin access.",
                     "evidence_id": "admin"},
                ],
            }],
        }],
    }


def knowledge(snapshot=None):
    return SiteKnowledge(discover(inventory() if snapshot is None else snapshot).products)


def test_first_step_is_sourced_and_explain_does_not_advance():
    catalog = knowledge()
    state, reply = start(catalog, "mock-translation", "missing-panel")
    assert reply.status == "awaiting_result"
    assert reply.step_id == "check-plugin"
    assert reply.source == "mock://plugin"
    assert reply.message.startswith("Verify the plugin.")
    assert explain(catalog, state) == "Check the plugin activation."
    assert state.attempts == ()


def test_failed_step_advances_once_then_success_ends():
    catalog = knowledge()
    state, _ = start(catalog, "mock-translation", "missing-panel")
    second, reply = advance(catalog, state, "failed")
    assert [a.step_id for a in second.attempts] == ["check-plugin"]
    assert reply.step_id == "check-admin"
    assert reply.source == "mock://admin"
    final, answer = advance(catalog, second, "worked")
    assert final.status == "resolved"
    assert answer.step_id is None
    assert [a.result for a in final.attempts] == ["failed", "worked"]
    with pytest.raises(ValueError):
        advance(catalog, final, "failed")


def test_failure_exhaustion_requires_escalation_without_auto_ticket():
    catalog = knowledge()
    state, _ = start(catalog, "mock-translation", "missing-panel")
    state, _ = advance(catalog, state, "failed")
    state, reply = advance(catalog, state, "failed")
    assert state.status == "escalation_required"
    assert reply.step_id is None
    assert len(state.attempts) == 2
    with pytest.raises(ValueError):
        advance(catalog, state, "failed")
    with pytest.raises(ValueError):
        explain(catalog, state)


def test_restart_from_export_and_resume_without_repeat():
    catalog = knowledge()
    state, _ = start(catalog, "mock-translation", "missing-panel")
    state, _ = advance(catalog, state, "failed")
    snapshot = deepcopy(state.export())
    resumed = restore(knowledge(), snapshot)
    assert resumed == state
    assert current(knowledge(), resumed).step_id == "check-admin"
    complete, _ = advance(knowledge(), resumed, "worked")
    assert complete.status == "resolved"
    assert restore(knowledge(), complete.export()) == complete


def test_first_step_success_stops_without_second_step():
    catalog = knowledge()
    state, _ = start(catalog, "mock-translation", "missing-panel")
    done, reply = advance(catalog, state, "worked")
    assert done.status == "resolved"
    assert len(done.attempts) == 1
    assert reply.source is None


@pytest.mark.parametrize("mutation", [
    lambda raw: raw.update(step_id="check-plugin"),
    lambda raw: raw["attempts"][0].update(step_id="check-admin"),
    lambda raw: raw["attempts"][0].update(evidence_id="fake"),
    lambda raw: raw["attempts"][0].update(result="worked"),
    lambda raw: raw.update(status="resolved"),
    lambda raw: raw.update(extra=True),
    lambda raw: raw.update(attempts=[{}]),
])
def test_forged_context_fails_closed(mutation):
    catalog = knowledge()
    state, _ = start(catalog, "mock-translation", "missing-panel")
    state, _ = advance(catalog, state, "failed")
    raw = state.export()
    mutation(raw)
    with pytest.raises(ValueError):
        restore(catalog, raw)


def test_removed_product_or_changed_version_cannot_continue():
    catalog = knowledge()
    state, _ = start(catalog, "mock-translation", "missing-panel")
    snapshot = inventory()
    snapshot["active"] = []
    with pytest.raises(ValueError):
        current(knowledge(snapshot), state)
    with pytest.raises(ValueError):
        restore(knowledge(snapshot), state.export())
    upgraded = inventory()
    upgraded["signals"][0]["version"] = "2"
    with pytest.raises(ValueError):
        advance(knowledge(upgraded), state, "failed")


def test_no_documented_procedure_and_unsupported_result():
    catalog = knowledge()
    with pytest.raises(ValueError):
        start(catalog, "missing", "missing-panel")
    with pytest.raises(ValueError):
        start(catalog, "mock-translation", "fabricated")
    state, _ = start(catalog, "mock-translation", "missing-panel")
    with pytest.raises(ValueError):
        advance(catalog, state, "maybe")
    assert current(catalog, state).step_id == "check-plugin"


def test_legacy_product_remains_supported_but_no_troubleshooting():
    snapshot = inventory()
    del snapshot["signals"][0]["troubleshooting"]
    with pytest.raises(ValueError):
        start(knowledge(snapshot), "mock-translation", "missing-panel")

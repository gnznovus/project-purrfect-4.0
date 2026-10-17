"""Goal 1.8c live chat routing without executing product operations."""
from copy import deepcopy

from purrfect.local_api import LocalState, respond


def registry():
    return {
        "active": [{"kind": "plugin", "key": "mock/plugin.php"}],
        "signals": [{
            "kind": "plugin", "key": "mock/plugin.php", "product_id": "mock-translation",
            "version": "1", "contract": 1, "capabilities": ["translate-content"],
            "knowledge": [
                {"id": "panel", "title": "Missing translation panel",
                 "text": "Check plugin status.", "source": "mock://panel",
                 "tags": ["translation", "panel", "missing"]},
                {"id": "access", "title": "Panel access",
                 "text": "Check administrator access.", "source": "mock://access",
                 "tags": ["access"]},
            ],
            "troubleshooting": [{
                "id": "missing-panel", "title": "Missing translation panel",
                "steps": [
                    {"id": "plugin", "instruction": "Check plugin status.",
                     "evidence_id": "panel"},
                    {"id": "admin", "instruction": "Check administrator access.",
                     "evidence_id": "access"},
                ],
            }],
        }],
    }


def send(state, session="a", message="", selection=None, context=None, inv=None):
    payload = {"session_id": session, "message": message, "selection": selection,
               "inventory": registry() if inv is None else inv}
    if context is not None:
        payload["context"] = context
    return respond(payload, state)


def begin(state, session="a"):
    first = send(state, session, "I need some help")
    assert first["interaction"]["key"] == "support_scope"
    result = send(state, session, selection="mock-translation")
    assert result["interaction"]["key"] == "support_intent"
    ids = [x["id"] for x in result["interaction"]["options"]]
    assert "troubleshoot:mock-translation:0" in ids
    step = send(state, session, selection="troubleshoot:mock-translation:0")
    assert step["status"] == "awaiting_result"
    assert step["sources"][0]["source"] == "mock://panel"
    assert {x["label"] for x in step["interaction"]["options"]} == {
        "It worked", "Didn't work", "Why this step?"
    }
    return step


def test_full_failure_flow_and_escalation_without_ticket():
    state = LocalState()
    first = begin(state)
    why = send(state, selection="check:plugin:why")
    assert "Check plugin status." in why["message"]
    assert why["context"]["troubleshooting"]["attempts"] == []
    second = send(state, selection="check:plugin:failed")
    assert second["status"] == "awaiting_result"
    assert second["sources"][0]["source"] == "mock://access"
    assert second["context"]["troubleshooting"]["step_id"] == "admin"
    stale = send(state, selection="check:plugin:worked")
    assert stale["status"] == "clarification"
    assert stale["context"]["troubleshooting"]["step_id"] == "admin"
    final = send(state, selection="check:admin:failed")
    assert final["status"] == "escalation_required"
    assert len(final["context"]["troubleshooting"]["attempts"]) == 2
    assert final["interaction"] is None
    assert "ticket" not in final["message"].lower()


def test_success_and_recovery_after_python_restart():
    first = begin(LocalState())
    restarted = LocalState()
    restored = send(restarted, selection="check:plugin:failed", context=first["context"])
    assert restored["context"]["troubleshooting"]["step_id"] == "admin"
    finished = send(LocalState(), message="it worked", context=restored["context"])
    assert finished["status"] == "resolved"
    assert finished["context"]["outcome"] == "resolved"
    assert len(finished["context"]["troubleshooting"]["attempts"]) == 2


def test_inactive_version_change_and_forged_state_rejected():
    step = begin(LocalState())
    inactive = registry()
    inactive["active"] = []
    response = send(LocalState(), selection="check:plugin:worked",
                    context=step["context"], inv=inactive)
    assert response["status"] == "clarification"
    assert "troubleshooting" not in response["context"]
    newer = registry()
    newer["signals"][0]["version"] = "2"
    response = send(LocalState(), selection="check:plugin:worked",
                    context=step["context"], inv=newer)
    assert response["status"] == "clarification"
    forged = deepcopy(step["context"])
    forged["troubleshooting"]["step_id"] = "admin"
    response = send(LocalState(), selection="check:plugin:worked", context=forged)
    assert response["status"] == "clarification"


def test_existing_guide_choice_and_new_sessions_still_work():
    state = LocalState()
    begin(state)
    assert send(state, session="b", selection="check:plugin:worked")["status"] == "clarification"
    selection = send(state, session="c", message="I need some help")
    choices = send(state, session="c", selection="mock-translation")
    assert "guide:mock-translation:0" in [x["id"] for x in choices["interaction"]["options"]]
    guide = send(state, session="c", selection="guide:mock-translation:0")
    assert guide["status"] == "grounded"
    assert guide["sources"][0]["id"] == "panel"


def test_plain_language_outcomes_require_short_unambiguous_confirmation():
    state = LocalState()
    begin(state)
    why = send(state, message="why this step")
    assert why["context"]["troubleshooting"]["attempts"] == []
    failed = send(state, message="didn't work")
    assert failed["context"]["troubleshooting"]["step_id"] == "admin"
    done = send(state, message="it worked")
    assert done["status"] == "resolved"

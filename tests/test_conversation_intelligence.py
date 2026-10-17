from purrfect.local_api import LocalState, respond
from test_local_api import request, ScriptedBrain


def guided(state, sid="conv"):
    first = respond(request(sid, "How do I edit layout blocks?"), state)
    assert first["status"] == "grounded"
    return first


def test_unresolved_then_resolved_keeps_topic():
    state = LocalState()
    original = guided(state)
    failed = respond(request("conv", "That didn't work."), state)
    assert "What happened" in failed["message"]
    assert failed["context"]["outcome"] == "unresolved"
    assert failed["context"]["last_question"] == original["context"]["last_question"]
    solved = respond(request("conv", "Thanks, it worked!"), state)
    assert solved["context"]["outcome"] == "resolved"
    assert solved["scope"] == "conversation"


def test_followup_does_not_invent_previous_step():
    state = LocalState()
    guided(state)
    response = respond(request("conv", "What about the previous step?"), state)
    assert response["status"] == "clarification"
    assert "doesn't specify" in response["message"]
    assert response["sources"] == []


def test_simplify_repeats_only_current_verified_instruction():
    state = LocalState()
    guided(state)
    response = respond(request("conv", "Can you explain that more simply?"), state)
    assert response["status"] == "grounded"
    assert "Open the layout editor to edit blocks." in response["message"]
    assert [source["id"] for source in response["sources"]] == ["a"]


def test_restart_restores_outcome_and_evidence():
    state = LocalState()
    guided(state)
    failed = respond(request("conv", "That didn't work."), state)
    restored = request("conv", "Can you explain that more simply?")
    restored["context"] = failed["context"]
    answer = respond(restored, LocalState())
    assert answer["status"] == "grounded"
    assert answer["context"]["evidence_id"] == "a"


def test_inactive_product_evidence_cannot_be_replayed():
    state = LocalState()
    original = guided(state)
    restored = request("conv", "Can you explain that more simply?",
                       registry={"active": [], "signals": []})
    restored["context"] = original["context"]
    answer = respond(restored, LocalState())
    assert answer["sources"] == []
    assert "Open the layout editor" not in answer["message"]


def test_correction_to_other_product_uses_current_inventory():
    state = LocalState(model=ScriptedBrain('{"selection":"mock-layout"}'))
    guided(state)
    answer = respond(request("conv", "No, I meant Layout Engine"), state)
    assert answer["scope"] == "product"
    assert answer["status"] in ("grounded", "needs_input")


def test_separate_sessions_keep_separate_outcomes():
    state = LocalState()
    guided(state, "one")
    guided(state, "two")
    respond(request("one", "That didn't work."), state)
    answer = respond(request("two", "Thanks, it worked!"), state)
    assert answer["context"]["outcome"] == "resolved"
    assert state.sessions["one"].outcome == "unresolved"


def test_invalid_outcome_cannot_be_restored():
    import pytest
    data = request("forged", "test")
    data["context"] = {"outcome": "admin", "evidence_id": "a"}
    with pytest.raises(ValueError):
        respond(data, LocalState())

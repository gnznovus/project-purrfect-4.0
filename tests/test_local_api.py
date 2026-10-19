from purrfect.local_api import LocalState, respond


def inventory():
    return {"active": [{"kind": "plugin", "key": "mock/mock.php"}], "signals": [{
        "kind": "plugin", "key": "mock/mock.php",
        "product_id": "mock-layout", "version": "1", "contract": 1,
        "capabilities": ["edit-layout"],
        "knowledge": [{"id": "a", "title": "Edit layout blocks",
                       "text": "Open the layout editor to edit blocks.",
                       "source": "mock://layout", "tags": ["layout", "edit"]}],
    }]}


def request(session, message, selection=None, registry=None):
    return {"session_id": session, "message": message,
            "selection": selection, "inventory": inventory() if registry is None else registry}


def test_question_and_interactive_selection():
    state = LocalState()
    first = respond(request("a", "I cannot edit my page"), state)
    assert first["status"] == "needs_input"
    assert {o["id"] for o in first["interaction"]["options"]} == {
        "mock-layout", "wordpress", "other"}
    resolved = respond(request("a", "", "mock-layout"), state)
    assert resolved["scope"] == "product"


def test_separate_sessions_and_removed_product():
    state = LocalState()
    respond(request("a", "layout edit"), state)
    respond(request("b", "login password"), state)
    dropped = {"active": [], "signals": []}
    result = respond(request("a", "", "mock-layout", dropped), state)
    assert result["status"] == "needs_input"
    assert respond(request("b", "", "wordpress"), state)["scope"] == "clarify"  # no pending choice


def test_unsupported_and_validation():
    state = LocalState()
    respond(request("a", "Help"), state)
    assert respond(request("a", "", "other"), state)["status"] == "unsupported"
    assert respond(request("missing", "", "mock-layout"), state)["status"] == "needs_input"
    try:
        respond(request("a", "", "mock-layout") | {"inventory": {"signals": []}}, state)
    except ValueError:
        pass
    else:
        raise AssertionError("Malformed inventory accepted")


def test_wordpress_password_question_returns_only_login_evidence():
    state = LocalState()
    result = respond(request("password-test", "I forgot my WordPress login password"), state)
    assert result["scope"] == "wordpress"
    assert result["status"] == "grounded"
    assert [source["id"] for source in result["sources"]] == ["wp-login-basic"]
    assert "password reset" in result["message"]
    assert "cache" not in result["message"].lower()
    assert "Edit option" not in result["message"]


def test_wordpress_unrelated_question_does_not_dump_faq():
    state = LocalState()
    result = respond(request("unknown-test", "WordPress quantum unicorn"), state)
    assert result["status"] == "needs_input"
    result = respond(request("unknown-test", "", "wordpress"), state)
    assert result["status"] == "needs_input"
    assert result["interaction"]["key"] == "support_intent"
    assert result["sources"] == []


class ScriptedBrain:
    def __init__(self, answer):
        self.answer = answer

    async def complete(self, system, user):
        return self.answer


def test_brain_verified_wordpress_answer_only():
    state = LocalState(model=ScriptedBrain('{"selection":"wordpress"}'))
    result = respond(request("brain-1", "I forgot my WordPress login password"), state)
    assert result["routing"] == "brain"
    assert [e["id"] for e in result["sources"]] == ["wp-login-basic"]


def test_brain_uncertainty_and_invented_product_clarify():
    for answer in ('{"selection":null}', '{"selection":"fake-product"}', 'not json'):
        state = LocalState(model=ScriptedBrain(answer))
        result = respond(request("brain-2", "I cannot edit my page"), state)
        assert result["status"] == "needs_input"
        assert result["routing"] == "brain-clarify"


def test_brain_rejects_deactivated_products():
    state = LocalState(model=ScriptedBrain('{"selection":"mock-layout"}'))
    removed = {"active": [], "signals": []}
    result = respond(request("brain-3", "Mock layout", registry=removed), state)
    assert result["status"] == "needs_input"
    assert result["routing"] == "brain-clarify"


def test_unavailable_model_degrades_to_clarification():
    class Broken:
        async def complete(self, system, user):
            raise ConnectionError("offline")
    state = LocalState(model=Broken())
    result = respond(request("brain-4", "help translate"), state)
    assert result["status"] == "needs_input"
    assert result["routing"] == "brain-unavailable"


def test_17_greeting_and_conversational_request():
    state = LocalState(model=ScriptedBrain('{"selection":"other"}'))
    for question in ("Hi Purra!", "Can I ask something else?"):
        response = respond(request("conversation", question), state)
        assert response["scope"] == "conversation"
        assert response["status"] == "grounded"
        assert response["sources"] == []


def test_17_restored_pending_selection_uses_current_registry():
    state = LocalState(model=ScriptedBrain('{"selection":null}'))
    pending = respond(request("old", "I cannot edit the page"), state)
    assert pending["status"] == "needs_input"
    new_state = LocalState()
    restore = request("old", "", "mock-layout")
    restore["context"] = {"last_question": "I cannot edit the page"}
    answer = respond(restore, new_state)
    assert answer["scope"] == "product"
    assert answer["status"] == "grounded"
    assert answer["context"]["last_scope"] == "mock-layout"
    removed = request("old", "", "mock-layout", {"active": [], "signals": []})
    removed["context"] = restore["context"]
    assert respond(removed, LocalState())["status"] == "needs_input"


def test_17_invalid_browser_context_rejected():
    state = LocalState()
    invalid = request("one", "test")
    invalid["context"] = {"last_question": "x" * 2001}
    import pytest
    with pytest.raises(ValueError):
        respond(invalid, state)


def test_17_followup_uses_original_topic_and_current_inventory():
    class CapturingBrain:
        def __init__(self):
            self.questions = []
        async def complete(self, system, user):
            import json
            self.questions.append(json.loads(user)["question"])
            return '{"selection":"mock-layout"}'
    brain = CapturingBrain()
    state = LocalState(model=brain)
    first = respond(request("follow", "How do I edit layout blocks?"), state)
    assert first["status"] == "grounded"
    next_payload = request("follow", "What about that step?")
    next_payload["context"] = first["context"]
    next_result = respond(next_payload, state)
    assert next_result["status"] == "clarification"
    assert next_result["context"]["last_question"] == first["context"]["last_question"]
    assert "previous step" in next_result["message"].lower()


def test_17_json_object_empty_context_first_message():
    import json
    payload = request("new-session", "Hi Purra!")
    payload["context"] = {}
    actual = json.loads(json.dumps(payload))
    assert isinstance(actual["context"], dict)
    response = respond(actual, LocalState())
    assert response["scope"] == "conversation"
    assert response["status"] == "grounded"


def test_17b_stale_choice_is_not_accepted_after_new_topic():
    state = LocalState()
    first = respond(request("a", "I cannot edit my page"), state)
    assert first["context"]["pending"] is True
    direct = respond(request("a", "I forgot login password"), state)
    assert direct["status"] == "grounded"
    stale = respond(request("a", "", "mock-layout"), state)
    assert stale["status"] == "needs_input"
    assert stale["sources"] == []


def test_17b_recover_pending_choice_after_server_restart():
    state = LocalState()
    answer = respond(request("a", "I cannot edit my page"), state)
    assert answer["context"]["pending"]
    recovered = request("a", "", "mock-layout")
    recovered["context"] = answer["context"]
    output = respond(recovered, LocalState())
    assert output["status"] == "grounded"
    assert output["context"]["last_scope"] == "mock-layout"
    assert output["context"]["pending"] is False


def test_17b_inactive_product_cannot_be_restored():
    state = LocalState()
    first = respond(request("a", "I cannot edit my page"), state)
    payload = request("a", "", "mock-layout", {"active": [], "signals": []})
    payload["context"] = first["context"]
    result = respond(payload, LocalState())
    assert result["status"] == "needs_input"
    assert result["sources"] == []


def test_17b_other_session_cannot_use_pending_choice():
    state = LocalState()
    respond(request("a", "I cannot edit my page"), state)
    result = respond(request("b", "", "mock-layout"), state)
    assert result["status"] == "needs_input"
    assert result["sources"] == []


def test_17b_interactive_intent_from_verified_evidence():
    state = LocalState()
    result = respond(request("guide", "Help with something"), state)
    assert result["status"] == "needs_input"
    product = respond(request("guide", "", "mock-layout"), state)
    assert product["status"] == "needs_input"
    assert product["interaction"]["key"] == "support_intent"
    assert product["interaction"]["options"] == [
        {"id": "guide:mock-layout:0", "label": "Edit layout blocks"}
    ]
    verified = respond(request("guide", "", "guide:mock-layout:0"), state)
    assert verified["status"] == "grounded"
    assert [x["id"] for x in verified["sources"]] == ["a"]


def test_17b_restored_intent_choice_rechecks_current_product():
    state = LocalState()
    respond(request("guide", "Help with something"), state)
    pending = respond(request("guide", "", "mock-layout"), state)
    restore = request("guide", "", "guide:mock-layout:0")
    restore["context"] = pending["context"]
    assert respond(restore, LocalState())["status"] == "grounded"
    restore["inventory"] = {"active": [], "signals": []}
    invalid = respond(restore, LocalState())
    assert invalid["sources"] == []
    assert invalid["status"] == "needs_input"


def test_17b_generic_help_offers_scope_choices_without_calling_model():
    class ModelMustNotRun:
        async def complete(self, system, user):
            raise AssertionError("Generic help must not invoke the Brain")
    state = LocalState(model=ModelMustNotRun())
    reply = respond(request("help-session", "i need some help"), state)
    assert reply["status"] == "needs_input"
    assert reply["interaction"]["key"] == "support_scope"
    assert reply["context"]["pending"] is True
    chosen = respond(request("help-session", "", "mock-layout"), state)
    assert chosen["status"] == "needs_input"
    assert chosen["interaction"]["key"] == "support_intent"
    guide = respond(request("help-session", "", "guide:mock-layout:0"), state)
    assert guide["status"] == "grounded"
    assert [x["id"] for x in guide["sources"]] == ["a"]


def test_17c_three_step_flow_and_correct_pending_scope():
    state = LocalState()
    scope = respond(request("flow", "I need some help"), state)
    assert scope["interaction"]["key"] == "support_scope"
    topics = respond(request("flow", "", "mock-layout"), state)
    assert topics["interaction"]["key"] == "support_intent"
    assert topics["context"]["last_scope"] == "mock-layout"
    # A forged topic for a different scope cannot be accepted.
    wrong = respond(request("flow", "", "guide:wordpress:0"), state)
    assert wrong["sources"] == []
    assert wrong["status"] == "needs_input"
    guide = respond(request("flow", "", "guide:mock-layout:0"), state)
    assert guide["status"] == "grounded"
    assert guide["message"] == "Open the layout editor to edit blocks."
    assert guide["context"]["pending"] is False


def test_17c_new_session_cannot_inherit_previous_choices():
    state = LocalState()
    respond(request("old-session", "I need some help"), state)
    respond(request("old-session", "", "mock-layout"), state)
    fresh = respond(request("fresh-session", "", "guide:mock-layout:0"), state)
    assert fresh["sources"] == []
    assert fresh["status"] == "needs_input"


def test_generic_help_variants_do_not_classify_as_outside_support():
    class AlwaysOther:
        async def complete(self, system, user):
            return '{"selection":"other"}'

    for message in ("i need some help here", "i need help here",
                    "Can you help me please?", "please help with this"):
        reply = respond(request("generic-" + message, message), LocalState(model=AlwaysOther()))
        assert reply["status"] == "needs_input"
        assert reply["interaction"]["key"] == "support_scope"
        assert "mock-layout" in {o["id"] for o in reply["interaction"]["options"]}


def test_dynamic_help_generates_validated_scope_buttons():
    class WelcomeBrain:
        async def complete(self, system, user):
            if "Reply ONLY with JSON keys" in system:
                return '{"response":"I can help! Which area is causing trouble?","options":[{"id":"mock-layout","label":"Layout help"},{"id":"wordpress","label":"WordPress basics"}]}'
            return '{"kind":"new","reply":null}'
    state = LocalState(model=WelcomeBrain())
    answer = respond(request("dynamic-help", "I need help"), state)
    assert answer["message"] == "I can help! Which area is causing trouble?"
    assert answer["interaction"]["options"] == [
        {"id": "mock-layout", "label": "Layout help"},
        {"id": "wordpress", "label": "WordPress basics"},
    ]
    assert answer["context"]["pending"] is True
    selected = respond(request("dynamic-help", "", "mock-layout"), state)
    assert selected["interaction"]["key"] == "support_intent"


def test_dynamic_options_cannot_invent_registered_product():
    class InventingBrain:
        async def complete(self, system, user):
            return '{"response":"Choose a tool.","options":[{"id":"unregistered-plugin","label":"Magic tool"}]}'
    result = respond(request("invented-choice", "I need help"), LocalState(model=InventingBrain()))
    assert result["status"] == "needs_input"
    assert {item["id"] for item in result["interaction"]["options"]} == {"mock-layout", "wordpress", "other"}


def test_dynamic_small_talk_without_options():
    class NiceBrain:
        async def complete(self, system, user):
            if "Reply ONLY with JSON keys" in system:
                return '{"response":"Doing well, thanks for asking! What is on your mind?","options":[]}'
            return '{"kind":"social","reply":"How can I help?"}'
    answer = respond(request("social-turn", "how are you today?"), LocalState(model=NiceBrain()))
    assert answer["message"] == "Doing well, thanks for asking! What is on your mind?"
    assert answer["interaction"] is None
    assert answer["scope"] == "conversation"


def test_social_chat_does_not_show_scope_buttons_even_if_model_suggests_them():
    class PushyBrain:
        async def complete(self, system, user):
            if "Reply ONLY with JSON keys" in system:
                return '{"response":"You are very welcome!","options":[{"id":"wordpress","label":"WordPress"}]}'
            return '{"kind":"social","reply":"You are very welcome!"}'
    state = LocalState(model=PushyBrain())
    for message in ("Hi Purr!", "How are you today?", "Thank you!"):
        answer = respond(request("no-button-social", message), state)
        assert answer["interaction"] is None
        assert answer["scope"] == "conversation"


def test_lost_user_is_guided_not_rejected_as_unsupported():
    class SupportBrain:
        async def complete(self, system, user):
            if "Reply ONLY with JSON keys" in system:
                return '{"response":"I can help you find a starting point. What are you working on?","options":[{"id":"wordpress","label":"WordPress basics"}]}'
            return '{"kind":"new","reply":null}'
    for message in ("I don't know where to start", "I'm confused", "I have no idea where to start"):
        answer = respond(request("lost-" + message, message), LocalState(model=SupportBrain()))
        assert answer["scope"] == "conversation"
        assert answer["interaction"]["key"] == "support_scope"
        assert answer["message"].startswith("I can help")
        assert answer["status"] != "unsupported"


def test_social_and_generic_help_use_one_model_call_each():
    class CountingBrain:
        def __init__(self):
            self.calls = []
        async def complete(self, system, user, **kwargs):
            self.calls.append((system, kwargs))
            return '{"response":"Happy to help! What would you like to explore?","options":[]}'
    for phrase in ("Hi Purr!", "How are you today?", "I need help"):
        brain = CountingBrain()
        answer = respond(request("one-call-" + phrase, phrase), LocalState(model=brain))
        assert len(brain.calls) == 1
        assert brain.calls[0][1]["temperature"] == 0.65
        assert answer["message"].startswith("Happy to help")

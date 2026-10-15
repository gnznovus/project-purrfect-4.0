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
    assert respond(request("b", "", "wordpress"), state)["scope"] == "wordpress"


def test_unsupported_and_validation():
    state = LocalState()
    respond(request("a", "Help"), state)
    assert respond(request("a", "", "other"), state)["status"] == "unsupported"
    assert respond(request("missing", "", "mock-layout"), state)["status"] == "clarification"
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
    assert result["status"] == "clarification"
    assert result["sources"] == []

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

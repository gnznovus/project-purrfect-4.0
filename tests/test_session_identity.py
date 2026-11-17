import pytest
from fastapi.testclient import TestClient

from purrfect.core.service import PurrCore
from purrfect.gateway.app import create_app
from purrfect.gateway.auth import CredentialRegistry
from purrfect.gateway.session_tokens import InvalidSession, SessionTickets

KEY = "session-test-key-longer-than-thirty-two-bytes"
REGISTRY = CredentialRegistry.from_json(
    '[{"token":"client-a-secret-credentials-12345","tenant_id":"a","products":[]},'
    '{"token":"client-b-secret-credentials-12345","tenant_id":"b","products":[]}]')


def client_headers(tenant="a"):
    return {"Authorization": "Bearer client-" + tenant + "-secret-credentials-12345"}


def test_session_tickets_are_unpredictable_and_tenant_bound():
    tickets = SessionTickets(KEY)
    first = tickets.issue("a")
    second = tickets.issue("a")
    assert first.session_id != second.session_id
    assert first.session_token != second.session_token
    assert tickets.verify(first.session_token, "a") == first.session_id
    with pytest.raises(InvalidSession):
        tickets.verify(first.session_token, "b")
    with pytest.raises(InvalidSession):
        tickets.verify(first.session_token[:-1] + ("A" if first.session_token[-1] != "A" else "B"), "a")
    with pytest.raises(InvalidSession):
        tickets.verify(None, "a")


def test_ticket_expiry(monkeypatch):
    import purrfect.gateway.session_tokens as module
    monkeypatch.setattr(module.time, "time", lambda: 1000)
    tickets = SessionTickets(KEY, lifetime=60)
    issued = tickets.issue("a")
    monkeypatch.setattr(module.time, "time", lambda: 1060)
    with pytest.raises(InvalidSession):
        tickets.verify(issued.session_token, "a")


def test_invalid_signing_configuration():
    with pytest.raises(ValueError):
        SessionTickets("short")
    with pytest.raises(ValueError):
        SessionTickets(KEY, lifetime=1)


def test_session_possession_required_for_json_and_sse():
    with TestClient(create_app(PurrCore(), REGISTRY, SessionTickets(KEY))) as client:
        a = client_headers("a")
        b = client_headers("b")
        first = client.post("/v1/sessions", headers=a)
        assert first.status_code == 200
        ticket = first.json()["session_token"]
        sid = first.json()["session_id"]
        assert len(sid) >= 32
        payload = {"session_id": sid, "message": "hi"}
        for endpoint in ("/v1/chat", "/v1/chat/stream"):
            assert client.post(endpoint, headers=a, json=payload).status_code == 401
            assert client.post(endpoint, headers=b | {"X-Purr-Session": ticket}, json=payload).status_code == 401
            assert client.post(endpoint, headers=a | {"X-Purr-Session": ticket},
                               json=payload | {"session_id": "another-session"}).status_code == 403
            valid = client.post(endpoint, headers=a | {"X-Purr-Session": ticket}, json=payload)
            assert valid.status_code == 200
        # New session does not authorize reading the first session's history.
        second_ticket = client.post("/v1/sessions", headers=a).json()["session_token"]
        mismatch = client.post("/v1/chat", headers=a | {"X-Purr-Session": second_ticket}, json=payload)
        assert mismatch.status_code == 403


def test_session_signing_key_rotation_revokes_tickets():
    issued = SessionTickets(KEY).issue("a")
    rotated = SessionTickets("different-key-longer-than-thirty-two-bytes")
    with pytest.raises(InvalidSession):
        rotated.verify(issued.session_token, "a")

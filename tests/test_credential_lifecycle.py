import json
import time

import pytest
from fastapi.testclient import TestClient
from purrfect.core.contracts import TenantContext
from purrfect.core.service import PurrCore
from purrfect.gateway.app import create_app
from purrfect.gateway.auth import CredentialRegistry
from purrfect.gateway.session_tokens import InvalidSession, SessionTickets


OLD = "legacy-application-secret-123456789"
NEW = "rotated-application-secret-123456789"
KEY1 = "signing-key-one-with-at-least-thirty-two-bytes"
KEY2 = "signing-key-two-with-at-least-thirty-two-bytes"


def configuration(**overrides):
    data = {"token": OLD, "tenant_id": "hotel", "products": ["booking"]}
    return json.dumps([data | overrides])


def test_rotating_client_keys_and_scoped_grants():
    credentials = CredentialRegistry.from_json(json.dumps([
        {"token": OLD, "tenant_id": "hotel", "products": ["booking"]},
        {"token": NEW, "tenant_id": "hotel", "products": ["booking"]},
    ]))
    assert credentials.resolve("Bearer " + OLD).tenant_id == "hotel"
    assert credentials.resolve("Bearer " + NEW).tenant_id == "hotel"
    assert credentials.resolve("Bearer invalid") is None
    assert credentials.resolve("Bearer ") is None
    assert credentials.resolve("Basic " + OLD) is None
    # No plaintext secrets retained on the dataclass.
    assert not hasattr(credentials._credentials[0], "token")
    assert OLD not in repr(credentials)
    revoked = CredentialRegistry.from_json(json.dumps([
        {"token": OLD, "tenant_id": "hotel", "products": ["booking"], "disabled": True},
        {"token": NEW, "tenant_id": "hotel", "products": ["booking"]},
    ]))
    assert revoked.resolve("Bearer " + OLD) is None
    assert revoked.resolve("Bearer " + NEW) is not None


def test_client_expiry_and_activation(monkeypatch):
    import purrfect.gateway.auth as auth
    monkeypatch.setattr(auth.time, "time", lambda: 1000)
    disabled = CredentialRegistry.from_json(configuration(disabled=True))
    future = CredentialRegistry.from_json(configuration(not_before=1001))
    expired = CredentialRegistry.from_json(configuration(expires_at=1000))
    current = CredentialRegistry.from_json(configuration(not_before=999, expires_at=1001))
    assert all(reg.resolve("Bearer " + OLD) is None for reg in (disabled, future, expired))
    assert current.resolve("Bearer " + OLD).tenant_id == "hotel"
    monkeypatch.setattr(auth.time, "time", lambda: 1001)
    assert current.resolve("Bearer " + OLD) is None
    assert future.resolve("Bearer " + OLD).tenant_id == "hotel"


@pytest.mark.parametrize("changes", [
    {"disabled": "false"},
    {"not_before": True},
    {"not_before": -1},
    {"expires_at": "tomorrow"},
    {"not_before": 10, "expires_at": 10},
    {"unknown_field": "x"},
])
def test_invalid_lifecycle_fails_closed(changes):
    with pytest.raises(ValueError):
        CredentialRegistry.from_json(configuration(**changes))


def test_duplicate_credentials_fail_closed():
    with pytest.raises(ValueError):
        CredentialRegistry.from_json(json.dumps([
            {"token": OLD, "tenant_id": "one", "products": []},
            {"token": OLD, "tenant_id": "two", "products": []},
        ]))


def test_overlapping_session_signing_keys_and_retirement():
    first = SessionTickets(KEY1)
    old = first.issue("hotel")
    during = SessionTickets(KEY2, previous_secrets=(KEY1,))
    new = during.issue("hotel")
    assert during.verify(old.session_token, "hotel") == old.session_id
    assert during.verify(new.session_token, "hotel") == new.session_id
    with pytest.raises(InvalidSession):
        first.verify(new.session_token, "hotel")
    retired = SessionTickets(KEY2)
    assert retired.verify(new.session_token, "hotel") == new.session_id
    with pytest.raises(InvalidSession):
        retired.verify(old.session_token, "hotel")
    with pytest.raises(InvalidSession):
        during.verify(old.session_token, "another-hotel")


def test_signing_key_validation():
    with pytest.raises(ValueError):
        SessionTickets(KEY1, previous_secrets=(KEY1,))
    with pytest.raises(ValueError):
        SessionTickets(KEY1, previous_secrets=("short",))
    with pytest.raises(ValueError):
        SessionTickets(KEY1, previous_secrets=(KEY2,) * 4)


def test_gateway_accepts_alternate_identity_verifier():
    class IdentityAdapter:
        def resolve(self, authorization):
            if authorization == "Bearer signed-external-client-proof":
                return TenantContext("external", frozenset({"demo"}))
            return None
    with TestClient(create_app(PurrCore(), IdentityAdapter(), SessionTickets(KEY1))) as client:
        auth = {"Authorization": "Bearer signed-external-client-proof"}
        response = client.post("/v1/sessions", headers=auth)
        assert response.status_code == 200
        result = client.post("/v1/chat", headers=auth | {
            "X-Purr-Session": response.json()["session_token"]
        }, json={"message": "hello"})
        assert result.status_code == 200
        assert result.json()["status"] == "conversation"
        assert client.post("/v1/sessions", headers={
            "Authorization": "Bearer invalid"
        }).status_code == 401

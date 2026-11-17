import pytest
from fastapi.testclient import TestClient
from purrfect.core.service import PurrCore
from purrfect.gateway.app import create_app
from purrfect.gateway.auth import CredentialRegistry
from purrfect.gateway.session_tokens import SessionTickets
from purrfect.infrastructure.scheduler import SchedulerOverloaded, SchedulerTimeout

A = "a-local-development-token-12345"
B = "b-local-development-token-12345"
SIGNING_KEY = "test-only-session-signing-key-with-32-or-more-bytes"


def registry():
    return CredentialRegistry.from_json(
        '[{"token":"' + A + '","tenant_id":"a","products":["demo"]},'
        '{"token":"' + B + '","tenant_id":"b","products":[]}]')


def app(core=None):
    return create_app(core or PurrCore(), registry(), SessionTickets(SIGNING_KEY))


def headers(client, token=A):
    auth = {"Authorization": "Bearer " + token}
    session = client.post("/v1/sessions", headers=auth)
    assert session.status_code == 200
    return auth | {"X-Purr-Session": session.json()["session_token"]}, session.json()["session_id"]


def test_authenticated_contract_and_scope():
    with TestClient(app()) as client:
        payload = {"message": "Hi!"}
        assert client.post("/v1/chat", json=payload).status_code == 401
        assert client.post("/v1/sessions").status_code == 401
        only_client = {"Authorization": "Bearer " + A}
        assert client.post("/v1/chat", json=payload, headers=only_client).status_code == 401
        h, sid = headers(client)
        result = client.post("/v1/chat", json=payload, headers=h)
        assert result.status_code == 200
        assert result.json()["session_id"] == sid
        assert result.json()["status"] == "conversation"
        assert client.get("/v1/health", headers=h).json()["status"] == "healthy"
        assert client.post("/v1/chat", json=payload | {"inventory": {}}, headers=h).status_code == 422
        assert client.post("/v1/chat", json=payload | {"product_id": "demo"}, headers=h).status_code == 422
        denied_h, _ = headers(client, B)
        denied = client.post("/v1/chat", json=payload | {"product_id": "demo", "product_version": "1"},
                             headers=denied_h)
        assert denied.status_code == 403
        allowed = client.post("/v1/chat", json=payload | {"product_id": "demo", "product_version": "1"},
                              headers=h)
        assert allowed.status_code == 200 and allowed.json()["status"] == "knowledge_gap"


def test_credentials_configuration_fail_closed():
    for config in ('[]', '[{"token":"short","tenant_id":"a","products":[]}]',
                   '[{"token":"abcdefghijklmnop","tenant_id":"a","products":["x","x"]}]'):
        with pytest.raises(ValueError):
            CredentialRegistry.from_json(config)


@pytest.mark.parametrize("error,expected", [(SchedulerOverloaded, 429), (SchedulerTimeout, 503)])
def test_scheduler_errors_map_to_backpressure(error, expected):
    class Model:
        async def complete(self, system, user):
            return "hello"
    class Scheduler:
        async def run(self, tenant, operation):
            raise error("busy")
    core = PurrCore(model=Model(), scheduler=Scheduler())
    with TestClient(app(core)) as client:
        h, _ = headers(client)
        result = client.post("/v1/chat", json={"message": "hi"}, headers=h)
        assert result.status_code == expected
        assert result.headers["retry-after"] == "2"

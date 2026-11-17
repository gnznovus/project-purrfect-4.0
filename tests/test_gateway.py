import pytest
from fastapi.testclient import TestClient
from purrfect.core.service import PurrCore
from purrfect.gateway.app import create_app
from purrfect.gateway.auth import CredentialRegistry
from purrfect.infrastructure.scheduler import SchedulerOverloaded, SchedulerTimeout

A = "a-local-development-token-12345"
B = "b-local-development-token-12345"


def registry():
    return CredentialRegistry.from_json(
        '[{"token":"' + A + '","tenant_id":"a","products":["demo"]},'
        '{"token":"' + B + '","tenant_id":"b","products":[]}]')


def test_authenticated_contract_and_scope():
    with TestClient(create_app(PurrCore(), registry())) as client:
        payload = {"session_id": "same", "message": "Hi!"}
        assert client.post("/v1/chat", json=payload).status_code == 401
        headers = {"Authorization": "Bearer " + A}
        result = client.post("/v1/chat", json=payload, headers=headers)
        assert result.status_code == 200
        assert result.json()["status"] == "conversation"
        assert client.get("/v1/health", headers=headers).json()["status"] == "healthy"
        assert client.post("/v1/chat", json=payload | {"inventory": {}}, headers=headers).status_code == 422
        assert client.post("/v1/chat", json=payload | {"product_id": "demo"}, headers=headers).status_code == 422
        denied = client.post("/v1/chat", json=payload | {"product_id": "demo", "product_version": "1"},
                             headers={"Authorization": "Bearer " + B})
        assert denied.status_code == 403
        allowed = client.post("/v1/chat", json=payload | {"product_id": "demo", "product_version": "1"},
                              headers=headers)
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
    with TestClient(create_app(core, registry())) as client:
        result = client.post("/v1/chat", json={"session_id": "s", "message": "hi"},
                             headers={"Authorization": "Bearer " + A})
        assert result.status_code == expected
        assert result.headers["retry-after"] == "2"

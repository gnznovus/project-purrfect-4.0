import asyncio
import pytest
from fastapi.testclient import TestClient
from purrfect.core.service import PurrCore
from purrfect.gateway.app import Admission, create_app
from purrfect.gateway.auth import CredentialRegistry

A="a-local-development-token-12345"
B="b-local-development-token-12345"

def app():
    registry=CredentialRegistry.from_json('[{"token":"'+A+'","tenant_id":"a","products":["demo"]},{"token":"'+B+'","tenant_id":"b","products":[]}]')
    return create_app(PurrCore(),registry)

def test_authenticated_contract_and_scope():
    with TestClient(app()) as client:
        payload={"session_id":"same","message":"Hi!"}
        assert client.post("/v1/chat",json=payload).status_code==401
        headers={"Authorization":"Bearer "+A}
        result=client.post("/v1/chat",json=payload,headers=headers)
        assert result.status_code==200
        assert result.json()["status"]=="conversation"
        assert client.get("/v1/health",headers=headers).json()["status"]=="healthy"
        assert client.post("/v1/chat",json=payload|{"inventory":{}},headers=headers).status_code==422
        assert client.post("/v1/chat",json=payload|{"product_id":"demo"},headers=headers).status_code==422
        denied=client.post("/v1/chat",json=payload|{"product_id":"demo","product_version":"1"},headers={"Authorization":"Bearer "+B})
        assert denied.status_code==403
        allowed=client.post("/v1/chat",json=payload|{"product_id":"demo","product_version":"1"},headers=headers)
        assert allowed.status_code==200 and allowed.json()["status"]=="knowledge_gap"

def test_credentials_configuration_fail_closed():
    for config in ('[]','[{"token":"short","tenant_id":"a","products":[]}]',
                   '[{"token":"abcdefghijklmnop","tenant_id":"a","products":["x","x"]}]'):
        with pytest.raises(ValueError):
            CredentialRegistry.from_json(config)

@pytest.mark.asyncio
async def test_bounded_admission_and_release():
    limiter=Admission(slots=1,waiting=0,queue_timeout=0.1)
    await limiter.acquire()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await limiter.acquire()
    assert exc.value.status_code==429
    await limiter.release()
    await limiter.acquire()
    await limiter.release()

@pytest.mark.asyncio
async def test_waiting_request_times_out():
    limiter=Admission(slots=1,waiting=1,queue_timeout=0.01)
    await limiter.acquire()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await limiter.acquire()
    assert exc.value.status_code==503
    await limiter.release()

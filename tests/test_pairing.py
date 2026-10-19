"""Pairing invariants: tenant isolation, one-time codes, persistence and revocation."""
from uuid import uuid7

import pytest
from fastapi.testclient import TestClient

from purrfect.pairing import PairingRegistry
from purrfect.pairing_api import create_app


def test_pairing_persists_and_isolation(tmp_path):
    db = tmp_path / "registry.sqlite"
    registry = PairingRegistry(db)
    assistant_a, site_a = str(uuid7()), str(uuid7())
    assistant_b, site_b = str(uuid7()), str(uuid7())
    code = registry.create_pairing_code()
    first = registry.pair(code=code, assistant_id=assistant_a, site_id=site_a,
                          site_url="https://site-a.example")
    assert first["status"] == "paired"
    assert registry.authenticate(assistant_a, first["credential"])["site_id"] == site_a
    assert registry.authenticate(assistant_b, first["credential"]) is None
    with pytest.raises(PermissionError):
        registry.pair(code=code, assistant_id=assistant_b, site_id=site_b,
                      site_url="https://site-b.example")
    code_b = registry.create_pairing_code()
    with pytest.raises(PermissionError):
        registry.pair(code=code_b, assistant_id=assistant_a, site_id=site_b,
                      site_url="https://site-b.example")
    second = registry.pair(code=code_b, assistant_id=assistant_b, site_id=site_b,
                           site_url="https://site-b.example")
    assert registry.authenticate(assistant_a, second["credential"]) is None
    registry.close()
    reopened = PairingRegistry(db)
    assert reopened.authenticate(assistant_b, second["credential"])["site_id"] == site_b
    assert reopened.revoke(assistant_a)
    assert reopened.authenticate(assistant_a, first["credential"]) is None
    reopened.close()


def test_fastapi_requires_credentials_and_enforces_uuid(tmp_path):
    app = create_app(tmp_path / "api.sqlite")
    with TestClient(app) as client:
        code = app.state.pairing_registry.create_pairing_code()
        assistant, site = str(uuid7()), str(uuid7())
        payload = dict(code=code, assistant_id=assistant, site_id=site,
                       site_url="https://site.example")
        assert client.post("/v1/assistants/pair", json=dict(payload, assistant_id="bad")).status_code == 422
        response = client.post("/v1/assistants/pair", json=payload)
        assert response.status_code == 201
        credential = response.json()["credential"]
        assert client.post("/v1/assistants/pair", json=payload).status_code == 403
        assert client.get("/v1/assistants/me").status_code == 422
        headers = {"X-Purr-Assistant-ID": assistant, "Authorization": "Bearer " + credential}
        current = client.get("/v1/assistants/me", headers=headers)
        assert current.status_code == 200
        assert current.json()["site_id"] == site
        assert client.get("/v1/assistants/me", headers={**headers, "Authorization": "Bearer wrong"}).status_code == 401

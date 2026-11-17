"""Hosted staging constraints and Railway files; no cloud credentials required."""
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from purrfect.deploy import deployment_config
from purrfect.infrastructure.runtime import build_app
from purrfect.operations.app import build_console
from purrfect.operations.store import BenchmarkStore


def test_entrypoint_requires_production_and_railway_port(monkeypatch):
    monkeypatch.setenv("PURR_ENV", "development")
    with pytest.raises(RuntimeError, match="production"):
        deployment_config("gateway")
    monkeypatch.setenv("PURR_ENV", "production")
    monkeypatch.setenv("PORT", "9191")
    assert deployment_config("gateway") == ("0.0.0.0", 9191)
    assert deployment_config("operations") == ("0.0.0.0", 9191)
    for value in ("-1", "0", "65536", "garbage"):
        monkeypatch.setenv("PORT", value)
        with pytest.raises(ValueError):
            deployment_config("gateway")


def test_hosted_operations_rejects_auto_auth(monkeypatch):
    monkeypatch.setenv("PURR_ENV", "production")
    monkeypatch.setenv("PURR_OPERATIONS_DEV_AUTO_AUTH", "1")
    with pytest.raises(RuntimeError, match="auto-auth"):
        deployment_config("operations")
    monkeypatch.setenv("PURR_OPERATIONS_DEV_AUTO_AUTH", "0")
    assert deployment_config("operations")[0] == "0.0.0.0"


def test_gateway_deployment_health_does_not_bypass_auth(monkeypatch):
    monkeypatch.setenv("PURR_CLIENTS_JSON", json.dumps([
        {"token": "gateway-staging-token-32-chars-long-example", "tenant_id": "stage", "products": ["demo"]}
    ]))
    monkeypatch.setenv("PURR_SESSION_SIGNING_KEY", "signing-key-32-characters-minimum-example")
    monkeypatch.setenv("PURR_SESSION_DB", "")
    monkeypatch.setenv("PURR_MODEL_BACKEND", "deterministic")
    with TestClient(build_app()) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        assert client.get("/v1/health").status_code == 401
        assert client.post("/v1/sessions").status_code == 401


def test_console_deployment_health_does_not_expose_auth(tmp_path):
    store = BenchmarkStore(tmp_path / "runs.db")
    app = build_console(
        operator_token="operator-secret-32-character-example",
        gateway_token="gateway-token-at-least-16",
        gateway_url="http://internal-gateway:8080",
        metrics_token=None,
        store=store,
    )
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.json() == {"status": "ok"}
        assert "operator-secret" not in response.text
        assert client.get("/api/runs").status_code == 401
        assert client.get("/api/auth/status").json() == {"auto_login": False}
    store.close()


def test_railway_config_isolated_services():
    root = Path(__file__).resolve().parents[1]
    assert "python:3.14-slim" in (root / "Dockerfile").read_text()
    for name in ("gateway", "operations"):
        data = json.loads((root / "deploy" / f"railway.{name}.json").read_text())
        assert data["deploy"]["healthcheckPath"] == "/healthz"
        assert data["deploy"]["startCommand"] == f"python -m purrfect.deploy {name}"
    ignored = (root / ".dockerignore").read_text()
    assert ".env" in ignored
    assert ".venv" in ignored

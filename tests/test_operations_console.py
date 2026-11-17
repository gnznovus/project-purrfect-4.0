"""Console integration tests use simulated Gateway responses, not real model calls."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from purrfect.operations.app import build_console
from purrfect.operations.benchmark import BenchmarkConfig, BenchmarkRunner, summarize
from purrfect.operations.store import BenchmarkStore
from purrfect.operations.telemetry import project


OPERATOR = "operator-only-example-key-at-least-32-characters"
GATEWAY = "gateway-private-client-token-123456"
MONITOR = "monitor-only-example-key-at-least-32-characters"


def gateway(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/health":
        return httpx.Response(200, json={"service": "purr-gateway", "status": "healthy"})
    if request.url.path == "/v1/sessions":
        if request.headers.get("authorization") != "Bearer " + GATEWAY:
            return httpx.Response(401)
        return httpx.Response(200, json={"session_id": "test", "session_token": "signed-session-ticket"})
    if request.url.path == "/v1/chat":
        if request.headers.get("x-purr-session") != "signed-session-ticket":
            return httpx.Response(401)
        return httpx.Response(200, json={"session_id": "test", "status": "conversation",
                                          "message": "sample reply", "sources": []})
    if request.url.path == "/internal/metrics":
        if request.headers.get("authorization") != "Bearer " + MONITOR:
            return httpx.Response(401)
        return httpx.Response(200, text=(
            '# TYPE purr_operation_seconds histogram\n'
            'purr_operation_seconds_sum{kind="inference",outcome="ok",tenant_bucket="1",route="other"} 0.4\n'
            'purr_operation_seconds_count{kind="inference",outcome="ok",tenant_bucket="1",route="other"} 2\n'
        ))
    return httpx.Response(404)


@pytest.fixture
def console(tmp_path):
    store = BenchmarkStore(tmp_path / "operations.db")
    app = build_console(
        operator_token=OPERATOR, gateway_token=GATEWAY,
        gateway_url="http://gateway.test", metrics_token=MONITOR,
        store=store, transport=httpx.MockTransport(gateway),
        model_label="Development model",
    )
    with TestClient(app) as client:
        yield client, store
    store.close()


def auth():
    return {"Authorization": "Bearer " + OPERATOR}


def test_console_requires_distinct_operator_credentials(console):
    client, _ = console
    assert client.get("/api/runs").status_code == 401
    assert client.get("/api/overview", headers={"Authorization": "Bearer " + GATEWAY}).status_code == 401
    assert client.get("/api/telemetry", headers={"Authorization": "Bearer " + MONITOR}).status_code == 401
    assert client.post("/api/benchmarks", json={"profile": "greeting", "samples": 1, "concurrency": 1}).status_code == 401
    assert client.get("/").status_code == 200
    page = client.get("/").text
    assert "Operations Console" in page
    assert "Gateway" in page
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/app.css").status_code == 200
    assert client.get("/api/runs", headers=auth()).status_code == 200
    assert client.get("/").headers["cache-control"] == "no-store"
    assert "default-src 'none'" in client.get("/").headers["content-security-policy"]


def test_full_benchmark_flow_and_history_persistence(console):
    client, store = console
    run = client.post("/api/benchmarks", headers=auth(), json={
        "profile": "greeting", "samples": 3, "concurrency": 2,
    })
    assert run.status_code == 200, run.text
    payload = run.json()
    assert payload["state"] == "completed"
    report = payload["report"]
    assert report["successes"] == 3 and report["failures"] == 0
    assert len(report["samples"]) == 3
    assert report["p95_ms"] is not None
    assert report["throughput_per_min"] >= 0
    assert not any("message" in sample for sample in report["samples"])
    assert client.get("/api/runs/"+payload["id"], headers=auth()).json()["id"] == payload["id"]
    assert client.get("/api/runs", headers=auth()).json()["runs"][0]["id"] == payload["id"]
    assert client.get("/api/overview", headers=auth()).json()["latest_run"]["id"] == payload["id"]
    second_store = BenchmarkStore(store._db.execute("PRAGMA database_list").fetchone()[2])
    assert second_store.get(payload["id"])["report"]["successes"] == 3
    second_store.close()


def test_overview_and_telemetry_are_safe(console):
    client, _ = console
    overview = client.get("/api/overview", headers=auth()).json()
    assert overview["gateway"]["status"] == "healthy"
    assert overview["model_label"] == "Development model"
    metrics = client.get("/api/telemetry", headers=auth()).json()
    assert metrics["available"]
    assert metrics["series"] == [{"kind": "inference", "count": 2, "errors": 0, "avg_ms": 200.0}]
    assert GATEWAY not in str(metrics) and MONITOR not in str(metrics)


@pytest.mark.parametrize("params", [
    {"profile": "arbitrary", "samples": 1, "concurrency": 1},
    {"profile": "greeting", "samples": 0, "concurrency": 1},
    {"profile": "greeting", "samples": 9, "concurrency": 1},
    {"profile": "greeting", "samples": 2, "concurrency": 3},
    {"profile": "greeting", "samples": 1, "concurrency": 1, "target_url": "http://metadata"},
])
def test_benchmark_guardrails(console, params):
    client, _ = console
    assert client.post("/api/benchmarks", headers=auth(), json=params).status_code == 422


def test_invalid_configuration_rejected(tmp_path):
    db = BenchmarkStore(tmp_path/"runs.db")
    with pytest.raises(ValueError):
        build_console(operator_token="short", gateway_token=GATEWAY,
                      gateway_url="http://gateway.test", metrics_token=None, store=db)
    with pytest.raises(ValueError):
        build_console(operator_token=OPERATOR, gateway_token=GATEWAY,
                      gateway_url="http://gateway.test/something", metrics_token=None, store=db)
    with pytest.raises(ValueError):
        build_console(operator_token=OPERATOR, gateway_token=GATEWAY,
                      gateway_url="http://user:password@gateway.test", metrics_token=None, store=db)
    db.close()


def test_resume_marks_orphan_runs_interrupted(tmp_path):
    path = tmp_path/"runs.db"
    store = BenchmarkStore(path)
    run_id = store.start(profile="greeting", model_label="x", samples=2, concurrency=1)
    store.close()
    resumed = BenchmarkStore(path)
    assert resumed.get(run_id)["state"] == "interrupted"
    resumed.close()


def test_telemetry_projection_drops_unknown_labels():
    assert project(
        'purr_operation_seconds_count{kind="inference",outcome="ok",tenant_bucket="raw-secret",route="other"} 999\n'
        'purr_operation_seconds_count{kind="inference",outcome="ok",tenant_bucket="0",route="other"} 3\n'
        'purr_operation_seconds_sum{kind="inference",outcome="ok",tenant_bucket="0",route="other"} 1.5'
    ) == [{"kind": "inference", "count": 3, "errors": 0, "avg_ms": 500.0}]


@pytest.mark.asyncio
async def test_bounded_runner_rejects_too_many_samples():
    runner = BenchmarkRunner(BenchmarkConfig("http://gateway.test", GATEWAY),
                             transport=httpx.MockTransport(gateway))
    with pytest.raises(ValueError):
        await runner.run(profile="greeting", samples=20, concurrency=2)


@pytest.mark.asyncio
async def test_http_failures_record_status_without_body():
    def failing(request):
        if request.url.path == "/v1/sessions":
            return httpx.Response(200, json={"session_token": "ticket"})
        return httpx.Response(503, text="private model failure description")
    runner = BenchmarkRunner(BenchmarkConfig("http://gateway.test", GATEWAY),
                             transport=httpx.MockTransport(failing))
    result = await runner.run(profile="greeting", samples=2, concurrency=1)
    assert result["failures"] == 2
    assert result["statuses"] == {"503": 2}
    assert "private model failure" not in str(result)
    assert result["p95_ms"] is None

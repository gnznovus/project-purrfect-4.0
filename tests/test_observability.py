"""Observability regression tests: finite labels, auth and actual queue/inference timing."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from purrfect.core.service import PurrCore
from purrfect.gateway.app import create_app
from purrfect.gateway.auth import CredentialRegistry
from purrfect.gateway.session_tokens import SessionTickets
from purrfect.infrastructure.instrumentation import InstrumentedScheduler
from purrfect.infrastructure.metrics import Metrics, tenant_bucket
from purrfect.infrastructure.scheduler import FairInferenceScheduler, SchedulerTimeout


AUTH = "local-observability-client-secret-123456789"
MONITOR = "monitor-secret-with-at-least-32-characters"


def test_metric_labels_are_bounded_and_do_not_expose_identity():
    metrics = Metrics()
    for i in range(150):
        metrics.observe("inference", "ok", 0.05, tenant=f"tenant-sensitive-{i}")
    payload = metrics.render()
    assert "tenant-sensitive" not in payload
    assert "session_id" not in payload
    assert "question" not in payload
    assert "purr_operation_seconds_count" in payload
    assert payload.count("purr_operation_seconds_count") <= 16
    assert tenant_bucket("tenant-a") == tenant_bucket("tenant-a")
    with pytest.raises(ValueError):
        metrics.observe("arbitrary-user-text", "ok", 0.1)
    with pytest.raises(ValueError):
        metrics.observe("inference", "ok", -1)


def test_scrape_requires_distinct_monitoring_secret():
    metrics = Metrics()
    verifier = CredentialRegistry.from_json(json.dumps([
        {"token": AUTH, "tenant_id": "hotel", "products": []},
    ]))
    with TestClient(create_app(PurrCore(), verifier, SessionTickets("test-signing-key-longer-than-thirty-two-bytes"),
                               metrics=metrics, metrics_token=MONITOR)) as client:
        assert client.get("/internal/metrics").status_code == 401
        assert client.get("/internal/metrics", headers={"Authorization": f"Bearer {AUTH}"}).status_code == 401
        assert client.get("/internal/metrics", headers={"Authorization": f"Bearer {MONITOR}"}).status_code == 200
        session = client.post("/v1/sessions", headers={"Authorization": f"Bearer {AUTH}"})
        assert session.status_code == 200
        result = client.post("/v1/chat", headers={
            "Authorization": f"Bearer {AUTH}",
            "X-Purr-Session": session.json()["session_token"],
        }, json={"message": "hello"})
        assert result.status_code == 200
        scrape = client.get("/internal/metrics", headers={"Authorization": f"Bearer {MONITOR}"})
        assert 'kind="request"' in scrape.text
        assert 'route="chat"' in scrape.text
        assert AUTH not in scrape.text and MONITOR not in scrape.text


def test_metrics_endpoint_disabled_without_monitor_token():
    metrics = Metrics()
    verifier = CredentialRegistry.from_json(json.dumps([
        {"token": AUTH, "tenant_id": "hotel", "products": []},
    ]))
    with TestClient(create_app(PurrCore(), verifier, SessionTickets("test-signing-key-longer-than-thirty-two-bytes"),
                               metrics=metrics)) as client:
        assert client.get("/internal/metrics").status_code == 404


@pytest.mark.asyncio
async def test_queue_and_model_execution_measured_separately():
    metrics = Metrics()
    scheduler = InstrumentedScheduler(
        FairInferenceScheduler(slots=1, max_waiting=1, queue_timeout=0.05, metrics=metrics), metrics,
    )
    running = asyncio.Event()
    release = asyncio.Event()

    async def slow():
        running.set()
        await release.wait()
        return "done"

    first = asyncio.create_task(scheduler.run("hotel", slow))
    await running.wait()
    with pytest.raises(SchedulerTimeout):
        await scheduler.run("another", lambda: asyncio.sleep(0))
    release.set()
    assert await first == "done"
    scrape = metrics.render()
    assert 'kind="queue_local",outcome="timeout"' in scrape
    assert 'kind="queue_local",outcome="ok"' in scrape
    assert 'kind="inference",outcome="ok"' in scrape
    # Timed-out requests never execute inference.
    assert 'kind="inference",outcome="ok",tenant_bucket="' in scrape

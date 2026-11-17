import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from purrfect.core.contracts import ChatCommand, TenantContext
from purrfect.core.service import PurrCore
from purrfect.gateway.app import create_app
from purrfect.gateway.auth import CredentialRegistry
from purrfect.gateway.session_tokens import SessionTickets
from purrfect.infrastructure.scheduler import FairInferenceScheduler
from purrfect.infrastructure.sessions import SQLiteSessions


A = TenantContext("tenant-a", frozenset())
B = TenantContext("tenant-b", frozenset())


@pytest.mark.asyncio
async def test_sqlite_history_survives_new_core_instance(tmp_path):
    path = tmp_path / "sessions.db"

    class Spy:
        def __init__(self):
            self.inputs = []
        async def complete(self, system, user):
            self.inputs.append(user)
            return "reply"

    first_model = Spy()
    first_store = SQLiteSessions(path)
    await PurrCore(model=first_model, sessions=first_store).respond(A, ChatCommand("s", "secret alpha"))
    first_store.close()

    next_model = Spy()
    second_store = SQLiteSessions(path)
    second = PurrCore(model=next_model, sessions=second_store)
    await second.respond(B, ChatCommand("s", "hello"))
    assert "secret alpha" not in next_model.inputs[-1]
    await second.respond(A, ChatCommand("s", "follow up"))
    assert "secret alpha" in next_model.inputs[-1]
    second_store.close()


@pytest.mark.asyncio
async def test_session_history_truncated(tmp_path):
    store = SQLiteSessions(tmp_path / "sessions.db", history_limit=2)
    for i in range(4):
        store.append("tenant", "session", str(i), str(i))
    assert store.read("tenant", "session") == (("2", "2"), ("3", "3"))
    store.close()


@pytest.mark.asyncio
async def test_live_chunks_and_completed_only_session_commit(tmp_path):
    store = SQLiteSessions(tmp_path / "sessions.db")
    class Model:
        async def stream(self, system, user):
            yield "hello "
            await asyncio.sleep(0)
            yield "world"
        async def complete(self, system, user):
            return "hello world"
    core = PurrCore(model=Model(), sessions=store,
                    scheduler=FairInferenceScheduler(slots=1))
    events = [event async for event in core.stream(A, ChatCommand("s", "hi"))]
    assert [x["event"] for x in events] == ["delta", "delta", "done"]
    assert "".join(x["data"]["text"] for x in events[:-1]) == "hello world"
    assert store.read("tenant-a", "s") == (("hi", "hello world"),)
    store.close()


@pytest.mark.asyncio
async def test_aborted_stream_not_committed(tmp_path):
    store = SQLiteSessions(tmp_path / "sessions.db")
    class Model:
        async def stream(self, system, user):
            yield "partial"
            await asyncio.Event().wait()
        async def complete(self, system, user):
            return "fallback"
    core = PurrCore(model=Model(), sessions=store,
                    scheduler=FairInferenceScheduler(slots=1))
    stream = core.stream(A, ChatCommand("s", "hi"))
    first = await stream.__anext__()
    assert first["data"]["text"] == "partial"
    await stream.aclose()
    assert store.read("tenant-a", "s") == ()
    # Cancellation has released the inference slot.
    assert (await core.respond(A, ChatCommand("s", "hello"))).message == "fallback"
    store.close()


def test_sse_contract_and_authentication():
    clients = CredentialRegistry.from_json(json.dumps([
        {"token": "dev-client-secret-token-1234", "tenant_id": "tenant-a", "products": []}
    ]))
    class Model:
        async def stream(self, system, user):
            yield "one"
            yield "two"
        async def complete(self, system, user):
            return "onetwo"
    with TestClient(create_app(PurrCore(model=Model()), clients, SessionTickets('test-only-signing-key-longer-than-thirty-two-bytes'))) as client:
        auth = {"Authorization": "Bearer dev-client-secret-token-1234"}
        ticket = client.post("/v1/sessions", headers=auth).json()["session_token"]
        body = {"message": "hello"}
        assert client.post("/v1/chat/stream", json=body).status_code == 401
        with client.stream("POST", "/v1/chat/stream", json=body, headers={
            "Authorization": "Bearer dev-client-secret-token-1234",
            "X-Purr-Session": ticket,
        }) as res:
            assert res.status_code == 200
            assert res.headers["content-type"].startswith("text/event-stream")
            data = "".join(res.iter_text())
        assert "event: delta" in data and "event: done" in data
        assert "onetwo" not in data  # two separate data events


def test_stream_errors_have_terminal_event():
    clients = CredentialRegistry.from_json(json.dumps([
        {"token": "dev-client-secret-token-1234", "tenant_id": "tenant-a", "products": []}
    ]))
    class Bad:
        async def complete(self, system, user):
            raise RuntimeError("internal private details")
    with TestClient(create_app(PurrCore(model=Bad()), clients, SessionTickets('test-only-signing-key-longer-than-thirty-two-bytes'))) as client:
        auth = {"Authorization": "Bearer dev-client-secret-token-1234"}
        ticket = client.post("/v1/sessions", headers=auth).json()["session_token"]
        res = client.post("/v1/chat/stream", json={"message": "hello"},
                          headers=auth | {"X-Purr-Session": ticket})
        assert res.status_code == 200
        assert "event: error" in res.text
        assert "internal private details" not in res.text

"""Real Redis integration tests (GitHub CI runs a local Redis service)."""
import asyncio
import os

import pytest

from purrfect.core.contracts import ChatCommand, TenantContext
from purrfect.core.service import PurrCore
from purrfect.infrastructure.redis_sessions import (
    RedisSessionCoordinator, RedisSessions, SessionBusy, SessionLeaseLost, _key,
)


@pytest.fixture
def clients():
    url = os.getenv("PURR_TEST_REDIS_URL")
    if not url:
        pytest.skip("Redis test service is not configured")
    import redis
    first = redis.Redis.from_url(url, decode_responses=True)
    second = redis.Redis.from_url(url, decode_responses=True)
    first.flushdb()
    yield first, second
    first.flushdb()
    first.close()
    second.close()


@pytest.mark.asyncio
async def test_shared_conversation_order_and_tenant_isolation(clients):
    a, b = clients
    namespace = "purr-integration-order"
    started = asyncio.Event()
    release = asyncio.Event()
    seen = []

    class Model:
        async def complete(self, system, user):
            seen.append(user)
            if "User: first" in user:
                started.set()
                await release.wait()
            return "ok"

    first = PurrCore(model=Model(), sessions=RedisSessions(a, namespace=namespace),
                     session_coordinator=RedisSessionCoordinator(a, namespace=namespace))
    second = PurrCore(model=Model(), sessions=RedisSessions(b, namespace=namespace),
                      session_coordinator=RedisSessionCoordinator(b, namespace=namespace))
    tenant = TenantContext("hotel-a", frozenset())
    other = TenantContext("hotel-b", frozenset())
    pending_a = asyncio.create_task(first.respond(tenant, ChatCommand("same", "first")))
    await started.wait()
    pending_b = asyncio.create_task(second.respond(tenant, ChatCommand("same", "second")))
    await asyncio.sleep(0.1)
    assert len(seen) == 1  # Worker B must not run inference on stale history.
    release.set()
    await asyncio.gather(pending_a, pending_b)
    assert "User: first" in seen[-1]
    assert second.sessions.read("hotel-a", "same") == (("first", "ok"), ("second", "ok"))
    assert second.sessions.read("hotel-b", "same") == ()
    await second.respond(other, ChatCommand("same", "other"))
    assert "User: first" not in seen[-1]


@pytest.mark.asyncio
async def test_busy_session_times_out_without_stale_write(clients):
    a, b = clients
    namespace = "purr-integration-busy"
    coord_a = RedisSessionCoordinator(a, namespace=namespace, wait_seconds=1)
    coord_b = RedisSessionCoordinator(b, namespace=namespace, wait_seconds=0.1)
    async with coord_a.lock("hotel", "same"):
        with pytest.raises(SessionBusy):
            async with coord_b.lock("hotel", "same"):
                pass
    async with coord_b.lock("hotel", "same"):
        store = RedisSessions(b, namespace=namespace)
        store.append("hotel", "same", "question", "answer")
    assert RedisSessions(a, namespace=namespace).read("hotel", "same") == (("question", "answer"),)


@pytest.mark.asyncio
async def test_expired_or_replaced_lease_cannot_commit(clients):
    a, b = clients
    namespace = "purr-integration-fence"
    coord = RedisSessionCoordinator(a, namespace=namespace)
    store = RedisSessions(a, namespace=namespace)
    async with coord.lock("hotel", "same"):
        # Simulate lease loss/replacement before persistence.
        lock_key = _key(namespace, "hotel", "same") + ":lock"
        b.set(lock_key, "new-owner-token", px=30000)
        with pytest.raises(SessionLeaseLost):
            store.append("hotel", "same", "stale", "answer")
    assert store.read("hotel", "same") == ()


@pytest.mark.asyncio
async def test_cancel_waiter_and_reacquire(clients):
    a, b = clients
    namespace = "purr-integration-cancel"
    coord_a = RedisSessionCoordinator(a, namespace=namespace)
    coord_b = RedisSessionCoordinator(b, namespace=namespace)
    async with coord_a.lock("hotel", "same"):
        async def wait():
            async with coord_b.lock("hotel", "same"):
                return "wrong"
        task = asyncio.create_task(wait())
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    async with coord_b.lock("hotel", "same"):
        assert True


@pytest.mark.asyncio
async def test_retention_is_bounded_and_expiring(clients):
    a, _ = clients
    namespace = "purr-integration-ttl"
    coordinator = RedisSessionCoordinator(a, namespace=namespace)
    store = RedisSessions(a, namespace=namespace, history_limit=2, idle_ttl=60)
    async with coordinator.lock("hotel", "same"):
        for i in range(4):
            store.append("hotel", "same", str(i), str(i))
    assert store.read("hotel", "same") == (("2", "2"), ("3", "3"))
    assert 0 < a.ttl(_key(namespace, "hotel", "same")) <= 60

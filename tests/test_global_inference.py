"""Two separate Redis connections represent independent Gateway workers."""
import asyncio
import os

import pytest
from purrfect.infrastructure.redis_inference import (
    GlobalInferenceLeaseLost, RedisInferenceScheduler,
)
from purrfect.infrastructure.scheduler import FairInferenceScheduler, SchedulerTimeout


@pytest.fixture
def clients():
    url = os.getenv("PURR_TEST_REDIS_URL")
    if not url:
        pytest.skip("Redis integration service not configured")
    import redis
    a = redis.Redis.from_url(url, decode_responses=True)
    b = redis.Redis.from_url(url, decode_responses=True)
    a.flushdb()
    yield a, b
    a.flushdb()
    a.close()
    b.close()


def scheduler(client, *, slots=1, tenant_slots=1, lease=3, wait=0.25):
    return RedisInferenceScheduler(
        client, namespace="integration-global", global_slots=slots,
        per_tenant_slots=tenant_slots, lease_seconds=lease,
        wait_seconds=wait,
        local_scheduler=FairInferenceScheduler(slots=4, max_waiting=8),
    )


@pytest.mark.asyncio
async def test_shared_slots_across_worker_instances(clients):
    a, b = clients
    first = scheduler(a)
    second = scheduler(b)
    running = asyncio.Event()
    allow_finish = asyncio.Event()
    entered = []

    async def block():
        entered.append("first")
        running.set()
        await allow_finish.wait()
        return "done"

    job = asyncio.create_task(first.run("hotel-a", block))
    await running.wait()
    with pytest.raises(SchedulerTimeout):
        await second.run("hotel-b", lambda: asyncio.sleep(0, result="should not run"))
    assert entered == ["first"]
    allow_finish.set()
    assert await job == "done"
    assert await second.run("hotel-b", lambda: asyncio.sleep(0, result="next")) == "next"


@pytest.mark.asyncio
async def test_tenant_cap_even_when_global_slots_available(clients):
    a, b = clients
    first = scheduler(a, slots=2)
    second = scheduler(b, slots=2)
    started = asyncio.Event()
    release = asyncio.Event()

    async def block():
        started.set()
        await release.wait()

    task = asyncio.create_task(first.run("same", block))
    await started.wait()
    with pytest.raises(SchedulerTimeout):
        await second.run("same", lambda: asyncio.sleep(0, result="denied"))
    assert await second.run("other", lambda: asyncio.sleep(0, result="allowed")) == "allowed"
    release.set()
    await task


@pytest.mark.asyncio
async def test_cancellation_releases_shared_slot(clients):
    a, b = clients
    first = scheduler(a)
    second = scheduler(b)
    started = asyncio.Event()

    async def hold():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(first.run("hotel", hold))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await second.run("other", lambda: asyncio.sleep(0, result="free")) == "free"


@pytest.mark.asyncio
async def test_expired_lease_prevents_successful_completion(clients):
    a, b = clients
    first = scheduler(a, lease=3)
    started = asyncio.Event()
    finish = asyncio.Event()
    async def slow():
        started.set()
        await finish.wait()
        return "stale"

    task = asyncio.create_task(first.run("hotel", slow))
    await started.wait()
    # Force lease expiry to simulate lost Redis permit.
    b.delete("integration-global:inference:{global}:leases")
    finish.set()
    with pytest.raises(GlobalInferenceLeaseLost):
        await task


@pytest.mark.asyncio
async def test_workers_can_run_at_global_capacity(clients):
    a, b = clients
    first = scheduler(a, slots=2, tenant_slots=1)
    second = scheduler(b, slots=2, tenant_slots=1)
    entered = asyncio.Event()
    release = asyncio.Event()
    started = []

    async def work(label):
        started.append(label)
        if len(started) == 2:
            entered.set()
        await release.wait()

    one = asyncio.create_task(first.run("a", lambda: work("a")))
    two = asyncio.create_task(second.run("b", lambda: work("b")))
    await asyncio.wait_for(entered.wait(), timeout=2)
    assert set(started) == {"a", "b"}
    release.set()
    await asyncio.gather(one, two)

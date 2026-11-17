import asyncio
import pytest
from purrfect.infrastructure.scheduler import FairInferenceScheduler, SchedulerOverloaded, SchedulerTimeout


@pytest.mark.asyncio
async def test_round_robin_by_tenant():
    scheduler = FairInferenceScheduler(slots=1, max_waiting=4, max_waiting_per_tenant=3)
    started = asyncio.Event()
    release = asyncio.Event()
    order = []

    async def job(label, block=False):
        async def work():
            order.append(label)
            if block:
                started.set()
                await release.wait()
            return label
        return await scheduler.run(label.split("-")[0], work)

    first = asyncio.create_task(job("a-1", block=True))
    await started.wait()
    second = asyncio.create_task(job("a-2"))
    await asyncio.sleep(0)
    third = asyncio.create_task(job("b-1"))
    await asyncio.sleep(0)
    fourth = asyncio.create_task(job("a-3"))
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(first, second, third, fourth) == ["a-1", "a-2", "b-1", "a-3"]
    assert order == ["a-1", "a-2", "b-1", "a-3"]


@pytest.mark.asyncio
async def test_per_tenant_queue_limit_and_overload():
    scheduler = FairInferenceScheduler(slots=1, max_waiting=4, max_waiting_per_tenant=1)
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking():
        started.set()
        await release.wait()
        return "finished"

    active = asyncio.create_task(scheduler.run("a", blocking))
    await started.wait()
    queued = asyncio.create_task(scheduler.run("a", lambda: asyncio.sleep(0, result="a-next")))
    await asyncio.sleep(0)
    with pytest.raises(SchedulerOverloaded):
        await scheduler.run("a", lambda: asyncio.sleep(0))
    # Other tenants can still enter the bounded queue.
    other = asyncio.create_task(scheduler.run("b", lambda: asyncio.sleep(0, result="b-next")))
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(active, queued, other) == ["finished", "a-next", "b-next"]


@pytest.mark.asyncio
async def test_timeout_frees_pending_capacity():
    scheduler = FairInferenceScheduler(slots=1, max_waiting=1, queue_timeout=0.01)
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking():
        started.set()
        await release.wait()

    active = asyncio.create_task(scheduler.run("a", blocking))
    await started.wait()
    with pytest.raises(SchedulerTimeout):
        await scheduler.run("b", lambda: asyncio.sleep(0))
    release.set()
    await active
    assert await scheduler.run("b", lambda: asyncio.sleep(0, result="ok")) == "ok"


@pytest.mark.asyncio
async def test_cancel_pending_request_releases_queue_slot():
    scheduler = FairInferenceScheduler(slots=1, max_waiting=1)
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking():
        started.set()
        await release.wait()

    active = asyncio.create_task(scheduler.run("a", blocking))
    await started.wait()
    pending = asyncio.create_task(scheduler.run("b", lambda: asyncio.sleep(0)))
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    replacement = asyncio.create_task(scheduler.run("c", lambda: asyncio.sleep(0, result="free")))
    await asyncio.sleep(0)
    release.set()
    await active
    assert await replacement == "free"


@pytest.mark.asyncio
async def test_cancel_granted_request_releases_worker():
    scheduler = FairInferenceScheduler(slots=1, max_waiting=0)
    started = asyncio.Event()

    async def blocking():
        started.set()
        await asyncio.Event().wait()

    running = asyncio.create_task(scheduler.run("a", blocking))
    await started.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert await scheduler.run("b", lambda: asyncio.sleep(0, result="available")) == "available"

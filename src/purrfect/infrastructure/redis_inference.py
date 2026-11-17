"""Atomic global inference admission shared by API workers.

A Redis ZSET tracks expiring permits; leases are renewed while work runs.
This bounds *admitted* calls at one Redis primary, but cannot fence an
already-running external model after a Redis failover or worker stall.
"""
import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from redis.exceptions import RedisError
from purrfect.infrastructure.coordination_errors import GlobalInferenceLeaseLost

from purrfect.infrastructure.scheduler import (
    FairInferenceScheduler, SchedulerOverloaded, SchedulerTimeout,
)

T = TypeVar("T")

# Redis server time prevents independent app-clock drift. All state changes
# are atomic and use the same hash-slot friendly key in clustered Redis.
_ACQUIRE = """
local now = redis.call('TIME')
local ms = now[1]*1000 + math.floor(now[2]/1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ms)
local current = redis.call('ZRANGE', KEYS[1], 0, -1)
if #current >= tonumber(ARGV[3]) then return 0 end
local count = 0
for _, member in ipairs(current) do
  if string.sub(member, 1, string.len(ARGV[2])+1) == ARGV[2] .. ':' then
    count = count + 1
  end
end
if count >= tonumber(ARGV[4]) then return 0 end
redis.call('ZADD', KEYS[1], ms + tonumber(ARGV[5]), ARGV[1])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[5])*2)
return 1
"""

_RENEW = """
local now = redis.call('TIME')
local ms = now[1]*1000 + math.floor(now[2]/1000)
local expires = redis.call('ZSCORE', KEYS[1], ARGV[1])
if not expires or tonumber(expires) <= ms then return 0 end
redis.call('ZADD', KEYS[1], ms + tonumber(ARGV[2]), ARGV[1])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[2])*2)
return 1
"""

_RELEASE = """
return redis.call('ZREM', KEYS[1], ARGV[1])
"""


class RedisInferenceScheduler:
    """Composes local tenant-fair queueing with a Redis global capacity gate.

    Cross-process acquisition uses bounded polling, NOT a globally fair FIFO.
    Each worker must use the same namespace/capacity to enforce the same pool.
    """

    def __init__(
        self,
        client,
        *,
        namespace: str = "purr",
        global_slots: int = 1,
        per_tenant_slots: int = 1,
        lease_seconds: int = 30,
        wait_seconds: float = 5.0,
        local_scheduler: FairInferenceScheduler | None = None,
        metrics=None,
    ):
        if (not namespace or global_slots < 1 or per_tenant_slots < 1
                or per_tenant_slots > global_slots or lease_seconds < 3 or wait_seconds <= 0):
            raise ValueError("Invalid global inference limits")
        self._metrics = metrics
        self._client = client
        self._key = f"{namespace}:inference:{{global}}:leases"
        self._slots = global_slots
        self._tenant_slots = per_tenant_slots
        self._lease_ms = lease_seconds * 1000
        self._wait_seconds = wait_seconds
        self._local = local_scheduler or FairInferenceScheduler()

    async def _eval(self, script: str, *args):
        return await asyncio.to_thread(self._client.eval, script, 1, self._key, *args)

    async def _renew(self, member: str, stop: asyncio.Event, lost: asyncio.Event):
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._lease_ms / 3000)
                return
            except TimeoutError:
                pass
            try:
                if await self._eval(_RENEW, member, self._lease_ms) != 1:
                    lost.set()
                    return
            except RedisError:
                lost.set()
                return

    async def _run_global(self, tenant: str, operation: Callable[[], Awaitable[T]]) -> T:
        # Unambiguous member prefix; never interpolate tenant into a Redis key.
        if not tenant or ":" in tenant:
            raise ValueError("Invalid tenant identifier for model admission")
        member = f"{tenant}:{secrets.token_urlsafe(24)}"
        started = time.monotonic()
        deadline = started + self._wait_seconds
        while True:
            # Redis failures are propagated: never fall back to local admission.
            if await self._eval(
                _ACQUIRE, member, tenant, self._slots, self._tenant_slots, self._lease_ms
            ) == 1:
                break
            left = deadline - time.monotonic()
            if left <= 0:
                if self._metrics:
                    self._metrics.observe("queue_global", "timeout", time.monotonic() - started, tenant=tenant)
                raise SchedulerTimeout("Global inference capacity wait timed out")
            await asyncio.sleep(min(0.05, left))

        if self._metrics:
            self._metrics.observe('queue_global', 'ok', time.monotonic() - started, tenant=tenant)
        stop = asyncio.Event()
        lost = asyncio.Event()
        renew_task = asyncio.create_task(self._renew(member, stop, lost))
        work = asyncio.create_task(operation())
        watcher = asyncio.create_task(lost.wait())
        try:
            done, _ = await asyncio.wait({work, watcher}, return_when=asyncio.FIRST_COMPLETED)
            if watcher in done or lost.is_set():
                raise GlobalInferenceLeaseLost("Global inference lease was lost")
            result = await work
            # Final renewal check protects completion after worker event-loop stalls.
            if await self._eval(_RENEW, member, self._lease_ms) != 1:
                raise GlobalInferenceLeaseLost("Global inference lease expired")
            return result
        finally:
            work.cancel()
            watcher.cancel()
            stop.set()
            renew_task.cancel()
            await asyncio.gather(work, watcher, renew_task, return_exceptions=True)
            try:
                await asyncio.shield(self._eval(_RELEASE, member))
            except RedisError:
                # TTL-based cleanup is the fallback after Redis unavailability.
                pass

    async def run(self, tenant: str, operation: Callable[[], Awaitable[T]]) -> T:
        return await self._local.run(tenant, lambda: self._run_global(tenant, operation))

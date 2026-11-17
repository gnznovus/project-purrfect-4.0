"""Bounded, cancelable, per-tenant round-robin admission for model inference.

Single event loop / process only. No durable jobs or distributed coordination.
"""
import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class SchedulerOverloaded(Exception):
    """The bounded pending queue is full."""


class SchedulerTimeout(Exception):
    """A request waited too long before receiving an inference slot."""


class FairInferenceScheduler:
    def __init__(
        self,
        slots: int = 1,
        max_waiting: int = 4,
        max_waiting_per_tenant: int = 2,
        queue_timeout: float = 5.0,
    ) -> None:
        if slots < 1 or max_waiting < 0 or max_waiting_per_tenant < 1 or queue_timeout <= 0:
            raise ValueError("Invalid scheduler limits")
        self._slots = slots
        self._max_waiting = max_waiting
        self._per_tenant = max_waiting_per_tenant
        self._timeout = queue_timeout
        self._running = 0
        self._waiting = 0
        self._queues: dict[str, deque[asyncio.Future[None]]] = {}
        self._order: deque[str] = deque()
        self._lock = asyncio.Lock()

    def _dispatch_locked(self) -> None:
        while self._running < self._slots and self._order:
            tenant = self._order.popleft()
            queue = self._queues[tenant]
            future = queue.popleft()
            self._waiting -= 1
            if queue:
                self._order.append(tenant)
            else:
                del self._queues[tenant]
            self._running += 1
            if not future.done():
                future.set_result(None)

    def _revoke_locked(self, tenant: str, future: asyncio.Future[None]) -> None:
        queue = self._queues.get(tenant)
        if queue is not None and future in queue:
            queue.remove(future)
            self._waiting -= 1
            if not queue:
                del self._queues[tenant]
                self._order.remove(tenant)
        elif future.done() and not future.cancelled() and future.exception() is None:
            # A permit was granted concurrently with cancellation or timeout.
            self._running -= 1
        self._dispatch_locked()

    async def run(self, tenant: str, operation: Callable[[], Awaitable[T]]) -> T:
        if not tenant:
            raise ValueError("Tenant required")
        future: asyncio.Future[None] | None = None
        async with self._lock:
            if self._running < self._slots and not self._order:
                self._running += 1
            else:
                queue = self._queues.get(tenant)
                if (self._waiting >= self._max_waiting or
                        (queue is not None and len(queue) >= self._per_tenant)):
                    raise SchedulerOverloaded("Inference queue is full")
                future = asyncio.get_running_loop().create_future()
                if queue is None:
                    queue = deque()
                    self._queues[tenant] = queue
                    self._order.append(tenant)
                queue.append(future)
                self._waiting += 1
                self._dispatch_locked()
        if future is not None:
            try:
                await asyncio.wait_for(asyncio.shield(future), timeout=self._timeout)
            except (asyncio.CancelledError, TimeoutError) as exc:
                async with self._lock:
                    self._revoke_locked(tenant, future)
                if isinstance(exc, TimeoutError):
                    raise SchedulerTimeout("Inference queue wait timed out") from None
                raise
        try:
            return await operation()
        finally:
            async with self._lock:
                self._running -= 1
                self._dispatch_locked()

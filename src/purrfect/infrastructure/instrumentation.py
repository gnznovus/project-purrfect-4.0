"""Inference timing adapter; Core remains independent of metrics details."""
import asyncio
import time


class InstrumentedScheduler:
    def __init__(self, scheduler, metrics):
        self._scheduler = scheduler
        self._metrics = metrics

    async def run(self, tenant, operation):
        async def measured():
            start = time.monotonic()
            try:
                result = await operation()
            except asyncio.CancelledError:
                self._metrics.observe("inference", "cancelled", time.monotonic() - start, tenant=tenant)
                raise
            except Exception:
                self._metrics.observe("inference", "error", time.monotonic() - start, tenant=tenant)
                raise
            self._metrics.observe("inference", "ok", time.monotonic() - start, tenant=tenant)
            return result
        return await self._scheduler.run(tenant, measured)

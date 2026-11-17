"""Bounded, live end-to-end Gateway benchmark driver.

Requests use the production Gateway auth/session contract. Only aggregate
timings and HTTP status metadata are returned; responses are discarded.
"""
import asyncio
import math
import statistics
import time
from dataclasses import dataclass

import httpx


PROFILES = {
    "greeting": "Hi! Can you introduce yourself briefly?",
    "guidance": "How can you help me learn to use a product?",
    "explanation": "Explain the difference between authentication and authorization in two sentences.",
}


@dataclass(frozen=True)
class BenchmarkConfig:
    gateway_url: str
    client_token: str
    model_label: str = "Configured Gateway"

    def __post_init__(self):
        if not self.client_token or not self.gateway_url:
            raise ValueError("Gateway URL and client credential are required")


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * percentile / 100
    low = math.floor(index)
    high = math.ceil(index)
    return round(sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (index - low), 2)


def summarize(samples: list[dict], wall_ms: float) -> dict:
    good = [sample["latency_ms"] for sample in samples if sample["ok"]]
    statuses: dict[str, int] = {}
    for sample in samples:
        key = str(sample["status"])
        statuses[key] = statuses.get(key, 0) + 1
    return {
        "successes": len(good),
        "failures": len(samples) - len(good),
        "wall_ms": round(wall_ms, 2),
        "throughput_per_min": round(len(samples) * 60000 / wall_ms, 2) if wall_ms > 0 else 0,
        "avg_ms": round(statistics.mean(good), 2) if good else None,
        "min_ms": round(min(good), 2) if good else None,
        "p50_ms": _percentile(good, 50),
        "p95_ms": _percentile(good, 95),
        "max_ms": round(max(good), 2) if good else None,
        "statuses": statuses,
        "samples": sorted(samples, key=lambda x: x["number"]),
    }


class BenchmarkRunner:
    def __init__(self, config: BenchmarkConfig, *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 45):
        if not 1 <= timeout <= 120:
            raise ValueError("Invalid benchmark timeout")
        self.config = config
        self._transport = transport
        self._timeout = timeout

    async def run(self, *, profile: str, samples: int, concurrency: int) -> dict:
        if profile not in PROFILES or not 1 <= samples <= 8 or not 1 <= concurrency <= 3 or concurrency > samples:
            raise ValueError("Invalid benchmark controls")

        limiter = asyncio.Semaphore(concurrency)
        headers = {"Authorization": "Bearer " + self.config.client_token}
        started = time.perf_counter()

        async with httpx.AsyncClient(
            base_url=self.config.gateway_url, transport=self._transport,
            timeout=httpx.Timeout(self._timeout), follow_redirects=False,
            trust_env=False,
        ) as client:
            async def sample(number: int) -> dict:
                async with limiter:
                    status: int | str = "network"
                    elapsed_ms = 0.0
                    try:
                        session = await client.post("/v1/sessions", headers=headers)
                        status = session.status_code
                        if session.status_code != 200:
                            return {"number": number, "ok": False, "status": status, "latency_ms": 0.0}
                        data = session.json()
                        session_token = data["session_token"]
                        if not isinstance(session_token, str):
                            raise ValueError("Gateway returned invalid session ticket")
                        start = time.perf_counter()
                        response = await client.post(
                            "/v1/chat",
                            headers=headers | {"X-Purr-Session": session_token},
                            json={"message": PROFILES[profile]},
                        )
                        elapsed_ms = (time.perf_counter() - start) * 1000
                        status = response.status_code
                        # The non-streaming contract returns 200 only with a valid response.
                        ok = status == 200 and isinstance(response.json().get("message"), str)
                        return {"number": number, "ok": ok, "status": status,
                                "latency_ms": round(elapsed_ms, 2)}
                    except (httpx.HTTPError, ValueError, KeyError, TypeError):
                        # Never include exception details (could contain URL/token).
                        return {"number": number, "ok": False, "status": "network" if status == "network" else "protocol",
                                "latency_ms": round(elapsed_ms, 2)}

            results = await asyncio.gather(*(sample(i + 1) for i in range(samples)))
        return summarize(results, (time.perf_counter() - started) * 1000)

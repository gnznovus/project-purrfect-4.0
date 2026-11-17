"""Bounded in-process operational histograms: no user content or raw tenant IDs."""
import hashlib
import math
import threading
from collections import defaultdict

BOUNDS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)
KINDS = frozenset({"request", "queue_local", "queue_global", "inference", "stream"})
OUTCOMES = frozenset({"ok", "error", "timeout", "overloaded", "cancelled", "lease_lost"})
ROUTES = frozenset({"chat", "stream", "session", "health", "other"})


def tenant_bucket(tenant: str) -> str:
    return str(hashlib.sha256(tenant.encode()).digest()[0] % 16)


class Metrics:
    """Bounded label cardinality; metrics are per-process and non-identifying."""
    def __init__(self):
        self._lock = threading.Lock()
        self._counts = defaultdict(int)
        self._sums = defaultdict(float)
        self._histograms = defaultdict(lambda: [0] * (len(BOUNDS) + 1))

    def observe(self, kind: str, outcome: str, duration: float,
                *, tenant: str | None = None, route: str = "other") -> None:
        if kind not in KINDS or outcome not in OUTCOMES or route not in ROUTES:
            raise ValueError("Unrecognized metrics label")
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("Invalid duration")
        labels = (kind, outcome, tenant_bucket(tenant) if tenant else "none",
                  route if kind in ("request", "stream") else "other")
        with self._lock:
            self._counts[labels] += 1
            self._sums[labels] += duration
            for i, bound in enumerate(BOUNDS):
                if duration <= bound:
                    self._histograms[labels][i] += 1
            self._histograms[labels][-1] += 1

    def render(self) -> str:
        lines = ["# HELP purr_operation_seconds Duration of provider operations.",
                 "# TYPE purr_operation_seconds histogram"]
        with self._lock:
            for labels, count in sorted(self._counts.items()):
                kind, outcome, bucket, route = labels
                base = (f'kind="{kind}",outcome="{outcome}",'
                        f'tenant_bucket="{bucket}",route="{route}"')
                hist = self._histograms[labels]
                for i, bound in enumerate(BOUNDS):
                    lines.append(f'purr_operation_seconds_bucket{{{base},le="{bound:g}"}} {hist[i]}')
                lines.append(f'purr_operation_seconds_bucket{{{base},le="+Inf"}} {hist[-1]}')
                lines.append(f'purr_operation_seconds_sum{{{base}}} {self._sums[labels]:.9f}')
                lines.append(f'purr_operation_seconds_count{{{base}}} {count}')
        return "\n".join(lines) + "\n"

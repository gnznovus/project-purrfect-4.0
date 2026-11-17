"""Project a safe, bounded slice of Gateway's Prometheus histograms."""
import re

# Explicit metric contract; ignore arbitrary metrics and label values.
_COUNT = re.compile(
    r'^purr_operation_seconds_count\{kind="(request|queue_local|queue_global|inference|stream)",'
    r'outcome="(ok|error|timeout|overloaded|cancelled|lease_lost)",'
    r'tenant_bucket="(?:none|[0-9]|1[0-5])",route="(?:chat|stream|session|health|other)"\} (\d+)$'
)
_SUM = re.compile(
    r'^purr_operation_seconds_sum\{kind="(request|queue_local|queue_global|inference|stream)",'
    r'outcome="(ok|error|timeout|overloaded|cancelled|lease_lost)",'
    r'tenant_bucket="(?:none|[0-9]|1[0-5])",route="(?:chat|stream|session|health|other)"\} ([0-9.eE+-]+)$'
)


def project(text: str) -> list[dict]:
    totals: dict[str, dict[str, float | int]] = {}
    for line in text.splitlines():
        count = _COUNT.fullmatch(line)
        duration = _SUM.fullmatch(line)
        if not count and not duration:
            continue
        matched = count or duration
        kind = matched.group(1)
        item = totals.setdefault(kind, {"count": 0, "seconds": 0.0, "errors": 0})
        if count:
            value = int(count.group(3))
            item["count"] += value
            if count.group(2) != "ok":
                item["errors"] += value
        else:
            value = float(duration.group(3))
            if 0 <= value < 1e12:
                item["seconds"] += value
    return [
        {"kind": kind, "count": item["count"], "errors": item["errors"],
         "avg_ms": round(item["seconds"] * 1000 / item["count"], 2) if item["count"] else None}
        for kind, item in sorted(totals.items())
    ]

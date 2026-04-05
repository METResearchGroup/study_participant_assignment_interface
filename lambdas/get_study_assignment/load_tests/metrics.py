"""Latency aggregation for load-test reporting."""

from __future__ import annotations

from typing import Any

import numpy as np

_PERCENTILES = (50, 90, 95, 99)


def summarize_ms(latencies_ms: list[float]) -> dict[str, Any]:
    """Summarize successful invocation latency values in milliseconds."""
    if not latencies_ms:
        return {
            "count": 0,
            "min_ms": None,
            "mean_ms": None,
            "p50_ms": None,
            "p90_ms": None,
            "p95_ms": None,
            "p99_ms": None,
            "max_ms": None,
        }

    arr = np.array(latencies_ms, dtype=float)
    percentiles = np.percentile(arr, _PERCENTILES)
    return {
        "count": int(arr.size),
        "min_ms": float(arr.min()),
        "mean_ms": float(arr.mean()),
        "p50_ms": float(percentiles[0]),
        "p90_ms": float(percentiles[1]),
        "p95_ms": float(percentiles[2]),
        "p99_ms": float(percentiles[3]),
        "max_ms": float(arr.max()),
    }

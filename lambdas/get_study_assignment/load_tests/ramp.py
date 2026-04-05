"""Linear ramp helpers for staged request submission."""

from __future__ import annotations


def stagger_seconds(index: int, n: int, ramp_seconds: float) -> float:
    """Return the offset from start-time for request index i in [0, n)."""
    if n <= 0:
        return 0.0
    if index < 0 or index >= n:
        raise ValueError(f"index must be in [0, {n}), got {index}")
    if ramp_seconds < 0:
        raise ValueError("ramp_seconds must be >= 0")
    return (index / n) * ramp_seconds

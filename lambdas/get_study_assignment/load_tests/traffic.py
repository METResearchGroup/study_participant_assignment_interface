"""Traffic shape generation for load-test requests."""

from __future__ import annotations

import random

PARTIES = ("democrat", "republican")
SCENARIOS = ("alternate", "random")
DEFAULT_SEED = 42


def parties_for_run(*, n: int, scenario: str, seed: int = DEFAULT_SEED) -> list[str]:
    """Return request political_party values for one run."""
    if n < 0:
        raise ValueError("n must be >= 0")
    if scenario not in SCENARIOS:
        raise ValueError(f"unsupported scenario={scenario!r}; expected one of {SCENARIOS}")
    if scenario == "alternate":
        return [PARTIES[i % 2] for i in range(n)]
    rng = random.Random(seed)
    return [rng.choice(PARTIES) for _ in range(n)]

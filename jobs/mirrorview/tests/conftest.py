"""Pytest configuration: project root on path and isolated RNG per test."""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pytest

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture(autouse=True)
def reset_precompute_rng():
    """Restore module RNG so tests do not depend on call order."""
    import jobs.mirrorview.precompute_assignments as pa

    pa.RNG = np.random.default_rng(pa.RANDOM_SEED)
    yield
    pa.RNG = np.random.default_rng(pa.RANDOM_SEED)

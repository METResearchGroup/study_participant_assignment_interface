"""Pytest configuration: isolated RNG per test."""

from __future__ import annotations

import numpy as np
import pytest

from lib.constants import ROOT_DIR  # noqa: F401 -- project root; imports use pytest pythonpath


@pytest.fixture(autouse=True)
def reset_precompute_rng():
    """Restore module RNG so tests do not depend on call order."""
    import jobs.mirrorview.precompute_assignments as pa

    pa.RNG = np.random.default_rng(pa.RANDOM_SEED)
    yield
    pa.RNG = np.random.default_rng(pa.RANDOM_SEED)

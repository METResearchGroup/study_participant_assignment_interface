from __future__ import annotations

import pytest

from lambdas.get_study_assignment.load_tests.metrics import summarize_ms


def test_summarize_ms_empty() -> None:
    summary = summarize_ms([])
    assert summary["count"] == 0
    assert summary["p95_ms"] is None


def test_summarize_ms_known_quantiles() -> None:
    summary = summarize_ms([10.0, 20.0, 30.0, 40.0, 50.0])
    assert summary["count"] == 5
    assert summary["min_ms"] == 10.0
    assert summary["mean_ms"] == 30.0
    assert summary["p50_ms"] == 30.0
    assert summary["p90_ms"] == pytest.approx(46.0)
    assert summary["p95_ms"] == pytest.approx(48.0)
    assert summary["p99_ms"] == pytest.approx(49.6)
    assert summary["max_ms"] == 50.0

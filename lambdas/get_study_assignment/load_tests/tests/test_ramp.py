from __future__ import annotations

import pytest

from lambdas.get_study_assignment.load_tests.ramp import stagger_seconds


def test_stagger_seconds_boundaries() -> None:
    assert stagger_seconds(index=0, n=5, ramp_seconds=10.0) == 0.0
    assert stagger_seconds(index=4, n=5, ramp_seconds=10.0) == pytest.approx(8.0)


def test_stagger_seconds_handles_non_positive_n() -> None:
    assert stagger_seconds(index=0, n=0, ramp_seconds=10.0) == 0.0
    assert stagger_seconds(index=0, n=-1, ramp_seconds=10.0) == 0.0


def test_stagger_seconds_rejects_out_of_range_index() -> None:
    with pytest.raises(ValueError, match="index must be in"):
        stagger_seconds(index=5, n=5, ramp_seconds=10.0)


def test_stagger_seconds_rejects_negative_ramp() -> None:
    with pytest.raises(ValueError, match="ramp_seconds must be >= 0"):
        stagger_seconds(index=0, n=5, ramp_seconds=-1.0)

from __future__ import annotations

import pytest

from lambdas.get_study_assignment.load_tests.traffic import parties_for_run


def test_alternate_parties_small_n() -> None:
    assert parties_for_run(n=1, scenario="alternate") == ["democrat"]
    assert parties_for_run(n=4, scenario="alternate") == [
        "democrat",
        "republican",
        "democrat",
        "republican",
    ]


def test_random_parties_are_seeded() -> None:
    first = parties_for_run(n=12, scenario="random", seed=42)
    second = parties_for_run(n=12, scenario="random", seed=42)
    assert first == second


def test_random_large_spot_check_matches_reference_vector() -> None:
    assert parties_for_run(n=8, scenario="random", seed=42) == [
        "democrat",
        "democrat",
        "republican",
        "democrat",
        "democrat",
        "democrat",
        "democrat",
        "democrat",
    ]


@pytest.mark.parametrize("n", [-1, -10])
def test_parties_for_run_rejects_negative_n(n: int) -> None:
    with pytest.raises(ValueError, match="n must be >= 0"):
        parties_for_run(n=n, scenario="alternate")

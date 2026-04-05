from __future__ import annotations

from collections import Counter

import pytest

from lambdas.get_study_assignment.load_tests.distribution_assertions import (
    assert_distribution,
    clopper_pearson_interval,
)


def test_clopper_pearson_interval_bounds() -> None:
    lo, hi = clopper_pearson_interval(5, 10)
    assert 0.0 <= lo < hi <= 1.0


def test_alternate_requires_divisible_by_four() -> None:
    with pytest.raises(ValueError, match="divisible by 4"):
        assert_distribution(
            scenario="alternate",
            request_condition_counts=Counter(
                {
                    ("democrat", "control"): 2,
                    ("democrat", "training_assisted"): 1,
                    ("republican", "control"): 1,
                    ("republican", "training_assisted"): 1,
                }
            ),
        )


def test_alternate_exact_counts_pass() -> None:
    result = assert_distribution(
        scenario="alternate",
        request_condition_counts=Counter(
            {
                ("democrat", "control"): 2,
                ("democrat", "training_assisted"): 2,
                ("republican", "control"): 2,
                ("republican", "training_assisted"): 2,
            }
        ),
    )
    assert result.ok
    assert not result.errors


def test_random_distribution_with_balanced_counts_passes() -> None:
    result = assert_distribution(
        scenario="random",
        request_condition_counts=Counter(
            {
                ("democrat", "control"): 500,
                ("democrat", "training_assisted"): 500,
                ("republican", "control"): 500,
                ("republican", "training_assisted"): 500,
            }
        ),
    )
    assert result.ok


def test_random_distribution_with_large_imbalance_fails() -> None:
    result = assert_distribution(
        scenario="random",
        request_condition_counts=Counter(
            {
                ("democrat", "control"): 950,
                ("democrat", "training_assisted"): 850,
                ("republican", "control"): 150,
                ("republican", "training_assisted"): 50,
            }
        ),
    )
    assert not result.ok
    assert any("failed" in err for err in result.errors)

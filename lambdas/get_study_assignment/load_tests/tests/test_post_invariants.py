from __future__ import annotations

import pandas as pd

from lambdas.get_study_assignment.load_tests.post_invariants import (
    validate_handler_assigned_post_ids,
)


def _make_ground_truth_and_valid_ids() -> tuple[pd.DataFrame, list[str]]:
    rows: list[dict[str, str]] = []
    post_ids: list[str] = []
    i = 0

    def add(n: int, stance: str, tox: str) -> None:
        nonlocal i
        for _ in range(n):
            pid = f"p{i:02d}"
            i += 1
            post_ids.append(pid)
            rows.append(
                {
                    "post_primary_key": pid,
                    "sampled_stance": stance,
                    "sample_toxicity_type": tox,
                }
            )

    add(3, "left", "sample_low_toxicity")
    add(2, "right", "sample_low_toxicity")
    add(5, "left", "sample_middle_toxicity")
    add(5, "right", "sample_middle_toxicity")
    add(2, "left", "sample_high_toxicity")
    add(3, "right", "sample_high_toxicity")
    df = pd.DataFrame(rows).set_index("post_primary_key")
    return df, post_ids


def test_validate_handler_assigned_post_ids_success() -> None:
    ground_truth, post_ids = _make_ground_truth_and_valid_ids()
    result = validate_handler_assigned_post_ids(
        assigned_post_ids_raw=post_ids,
        ground_truth_post_pool=ground_truth,
        context="ok",
    )
    assert result.valid
    assert result.error is None


def test_validate_handler_assigned_post_ids_unknown_post() -> None:
    ground_truth, post_ids = _make_ground_truth_and_valid_ids()
    bad = list(post_ids)
    bad[-1] = "missing-post"
    result = validate_handler_assigned_post_ids(
        assigned_post_ids_raw=bad,
        ground_truth_post_pool=ground_truth,
        context="bad",
    )
    assert not result.valid
    assert result.error is not None

"""Shared validation helpers for MirrorView assigned post bundles."""

from __future__ import annotations

import json

import pandas as pd

import jobs.mirrorview.precompute_assignments as pre


def infer_oversample_left(left_n: int, right_n: int) -> bool:
    """Infer the oversample mode from left/right stance totals."""
    if left_n == 11 and right_n == 9:
        return True
    if left_n == 10 and right_n == 10:
        return False
    raise AssertionError(
        "Left/right counts must be 11/9 (oversample left on high-toxicity) or 10/10 "
        f"(oversample right); got {left_n}/{right_n}"
    )


def get_post_ids_list(raw_post_ids: object, context: str) -> list[str]:
    """Parse assigned_post_ids payload into list[str]."""
    if isinstance(raw_post_ids, str):
        post_ids = json.loads(raw_post_ids)
    else:
        post_ids = raw_post_ids
    if not isinstance(post_ids, list):
        raise TypeError(f"{context}: assigned_post_ids must decode to a list")
    for pid in post_ids:
        if not isinstance(pid, str):
            raise TypeError(f"{context}: assigned_post_ids must be a list of strings")
    return post_ids


def validate_assigned_post_ids(post_ids: list[str], ground_truth_df: pd.DataFrame) -> None:
    """Validate one assigned 20-post bundle against MirrorView invariants."""
    rows: list[dict[str, str]] = []
    for pid in post_ids:
        if pid not in ground_truth_df.index:
            raise ValueError(f"unknown post_primary_key {pid!r}")
        row = ground_truth_df.loc[pid]
        rows.append(
            {
                "sample_toxicity_type": str(row["sample_toxicity_type"]),
                "sampled_stance": str(row["sampled_stance"]),
            }
        )
    sampled = pd.DataFrame(rows)
    total_left_leaning_posts = int((sampled["sampled_stance"] == "left").sum())
    total_right_leaning_posts = int((sampled["sampled_stance"] == "right").sum())
    oversample_left = infer_oversample_left(total_left_leaning_posts, total_right_leaning_posts)
    pre._validate_assignment_invariants(sampled, oversample_left)

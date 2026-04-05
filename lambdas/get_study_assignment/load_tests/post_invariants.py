"""Assigned-post invariant checks for load-test successes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

import jobs.mirrorview.precompute_assignments as pre
from lib.mirrorview_assignment_validate import get_post_ids_list, validate_assigned_post_ids


def load_ground_truth_post_pool(input_posts_path: Path = pre.INPUT_POSTS_PATH) -> pd.DataFrame:
    ground_truth = pd.read_csv(input_posts_path)
    return ground_truth.set_index("post_primary_key")


@dataclass(frozen=True)
class PostInvariantResult:
    valid: bool
    error: str | None = None


def validate_handler_assigned_post_ids(
    *,
    assigned_post_ids_raw: Any,
    ground_truth_post_pool: pd.DataFrame,
    context: str,
) -> PostInvariantResult:
    try:
        post_ids = get_post_ids_list(assigned_post_ids_raw, context)
        validate_assigned_post_ids(post_ids, ground_truth_post_pool)
    except Exception as exc:
        return PostInvariantResult(valid=False, error=f"{context}: {exc}")
    return PostInvariantResult(valid=True, error=None)

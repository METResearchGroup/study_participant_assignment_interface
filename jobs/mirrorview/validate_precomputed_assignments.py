"""Validate on-disk precomputed MirrorView assignment CSVs against precompute invariants.

Expects the same layout as `precompute_assignments.write_assignments`:
`<series_root>/{political_party}/{study_condition}/assignments.csv`
for each configured cell in the YAML config.

Usage (from repo root):

    uv run python -m jobs.mirrorview.validate_precomputed_assignments \\
        --config jobs/mirrorview/config/default.yaml \\
        --path data/mirrorview/2026_04_03-09:36:03
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

import jobs.mirrorview.precompute_assignments as pre
from jobs.mirrorview.config_loader import (
    MirrorViewConfig,
    load_mirrorview_config,
    resolve_repo_path,
)
from jobs.mirrorview.constants import OUTPUT_RECORDS_FILENAME
from lib.constants import ROOT_DIR

_EXPECTED_ASSIGNMENT_COLUMNS = (
    "id",
    "assigned_post_ids",
    "political_party",
    "condition",
    "created_at",
)
_PASS = "\033[32m[PASS]\033[0m"
_FAIL = "\033[31m[FAIL]\033[0m"


def _format_expected_actual(*, expected: str, actual: str) -> str:
    return f"Expected: {expected}, Actual: {actual}"


def _log_pass(check: str, *, expected: str, actual: str) -> None:
    print(
        f"{_PASS} {check} | {_format_expected_actual(expected=expected, actual=actual)}",
        flush=True,
    )


def _log_fail(check: str, *, expected: str, actual: str) -> None:
    print(
        f"{_FAIL} {check} | {_format_expected_actual(expected=expected, actual=actual)}",
        file=sys.stderr,
        flush=True,
    )


def _cell_label(political_party: str, condition: str) -> str:
    return f"{political_party}/{condition}"


class AssignmentCoverageTracker:
    """Accumulate post-assignment coverage stats across all configured cells in a batch.

    Used when the MirrorView config specifies ``expected_total_unique_posts`` and/or
    ``expected_min_assignments_per_post``. The tracker is updated once per assignment
    row and checked after every cell has been validated.
    """

    def __init__(
        self,
        ground_truth_post_ids: pd.Index,
        *,
        min_assignments_per_post: int | None,
        track_unique_posts: bool,
    ) -> None:
        """Initialize counters from the ground-truth post pool.

        When ``min_assignments_per_post`` is set, each post starts with that count;
        each assignment appearance decrements it until the post is removed at zero.
        """
        self._track_unique_posts = track_unique_posts
        self._assigned_unique_posts: set[str] = set()
        self._remaining_min_counts: dict[str, int] = {}
        if min_assignments_per_post is not None:
            self._remaining_min_counts = {
                str(post_id): min_assignments_per_post for post_id in ground_truth_post_ids
            }

    def record_assignment(self, post_ids: list[str]) -> None:
        """Record one participant assignment's post IDs for coverage tracking."""
        for post_id in post_ids:
            if self._track_unique_posts:
                self._assigned_unique_posts.add(post_id)
            if post_id in self._remaining_min_counts:
                self._remaining_min_counts[post_id] -= 1
                if self._remaining_min_counts[post_id] == 0:
                    del self._remaining_min_counts[post_id]

    @property
    def unique_assigned_post_count(self) -> int:
        """Number of distinct post IDs seen in any assignment across the batch."""
        return len(self._assigned_unique_posts)

    @property
    def posts_below_min_assignment_count(self) -> int:
        """Number of posts not yet assigned the configured minimum number of times."""
        return len(self._remaining_min_counts)


def _create_coverage_tracker_if_exists(
    config: MirrorViewConfig,
    ground_truth_post_pool: pd.DataFrame,
) -> AssignmentCoverageTracker | None:
    """Return a coverage tracker when the config defines coverage expectations.

    Returns ``None`` when neither ``expected_total_unique_posts`` nor
    ``expected_min_assignments_per_post`` is set (e.g. ``default.yaml``).
    """
    track_unique_posts = config.expected_total_unique_posts is not None
    min_assignments_per_post = config.expected_min_assignments_per_post
    if not track_unique_posts and min_assignments_per_post is None:
        return None
    return AssignmentCoverageTracker(
        ground_truth_post_pool.index,
        min_assignments_per_post=min_assignments_per_post,
        track_unique_posts=track_unique_posts,
    )


def _validate_unique_assigned_posts(
    tracker: AssignmentCoverageTracker,
    *,
    expected_total_unique_posts: int,
) -> None:
    """Verify the batch assigned every expected unique post at least once.

    Compares the tracker's distinct assigned post count against
    ``expected_total_unique_posts`` from the config. Logs pass/fail and raises on
    mismatch.
    """
    actual = tracker.unique_assigned_post_count
    if actual == expected_total_unique_posts:
        _log_pass(
            "unique_assigned_posts",
            expected=str(expected_total_unique_posts),
            actual=str(actual),
        )
        return
    _log_fail(
        "unique_assigned_posts",
        expected=str(expected_total_unique_posts),
        actual=str(actual),
    )
    raise AssertionError(
        f"Unique assigned post count mismatch: expected {expected_total_unique_posts}, got {actual}"
    )


def _validate_min_assignments_per_post(
    tracker: AssignmentCoverageTracker,
    *,
    expected_min_assignments_per_post: int,
) -> None:
    """Verify each post appears at least the configured number of times in the batch.

    Posts still in the tracker's remaining-count map were assigned fewer than
    ``expected_min_assignments_per_post`` times. Logs pass/fail and raises when any
    posts remain below the minimum.
    """
    posts_below_minimum = tracker.posts_below_min_assignment_count
    expected = (
        f"each post assigned at least {expected_min_assignments_per_post} times "
        f"(0 posts below minimum)"
    )
    if posts_below_minimum == 0:
        _log_pass(
            "min_assignments_per_post",
            expected=expected,
            actual="0 posts below minimum",
        )
        return
    _log_fail(
        "min_assignments_per_post",
        expected=expected,
        actual=f"{posts_below_minimum} posts below minimum",
    )
    raise AssertionError(
        f"{posts_below_minimum} posts appear fewer than "
        f"{expected_min_assignments_per_post} times across the batch"
    )


def _infer_oversample_left(left_n: int, right_n: int) -> bool:
    if left_n == 11 and right_n == 9:
        return True
    if left_n == 10 and right_n == 10:
        return False
    raise AssertionError(
        "Left/right counts must be 11/9 (oversample left on high-toxicity) or 10/10 "
        f"(oversample right); got {left_n}/{right_n}"
    )


def _get_ground_truth_sample_toxicity_political_stance(
    *,
    post_ids: list[str],
    ground_truth_post_pool: pd.DataFrame,
    context: str,
) -> pd.DataFrame:
    """For the given row ID, get the ground truth sample toxicity + stance."""
    rows: list[dict[str, str]] = []
    for pid in post_ids:
        if pid not in ground_truth_post_pool.index:
            raise ValueError(f"{context}: unknown post_primary_key {pid!r}")
        row = ground_truth_post_pool.loc[pid]
        rows.append(
            {
                "sample_toxicity_type": str(row["sample_toxicity_type"]),
                "sampled_stance": str(row["sampled_stance"]),
            }
        )
    return pd.DataFrame(rows)


def _validate_csv_file_exists(
    csv_path: Path,
    *,
    political_party: str,
    condition: str,
    config: MirrorViewConfig,
) -> None:
    cell = _cell_label(political_party, condition)
    expected = f"assignments file for config {config.name!r} cell {cell} at {csv_path}"
    if csv_path.is_file():
        _log_pass(f"{cell}: file exists", expected=expected, actual="file")
        return
    actual = "missing" if not csv_path.exists() else "path exists but is not a file"
    _log_fail(f"{cell}: file exists", expected=expected, actual=actual)
    raise FileNotFoundError(
        "Expected assignments file missing for configured cell "
        f"(expected paths from config {config.name!r}): {csv_path}"
    )


def _validate_no_missing_columns(
    df: pd.DataFrame,
    *,
    political_party: str,
    condition: str,
) -> None:
    cell = _cell_label(political_party, condition)
    expected_columns = ", ".join(_EXPECTED_ASSIGNMENT_COLUMNS)
    missing = [c for c in _EXPECTED_ASSIGNMENT_COLUMNS if c not in df.columns]
    if not missing:
        _log_pass(
            f"{cell}: schema",
            expected=f"columns [{expected_columns}]",
            actual=f"columns [{expected_columns}]",
        )
        return
    actual_columns = ", ".join(df.columns)
    _log_fail(
        f"{cell}: schema",
        expected=f"columns [{expected_columns}]",
        actual=f"missing [{', '.join(missing)}]; found [{actual_columns}]",
    )
    raise ValueError(f"{cell}: missing columns {missing}")


def get_post_ids_list(raw_post_ids: str, context: str) -> list[str]:
    """Validates that the assigned post IDs are a list of strings."""
    post_ids = json.loads(str(raw_post_ids))
    if not isinstance(post_ids, list):
        raise TypeError(f"{context}: assigned_post_ids must decode to a list")
    for pid in post_ids:
        if not isinstance(pid, str):
            raise TypeError(f"{context}: assigned_post_ids must be a list of strings")
    return post_ids


def _validate_expected_condition(
    row_condition: str, context: str, condition: str, political_party: str
) -> None:
    if row_condition != condition:
        raise AssertionError(
            f"{context}: column 'condition' is {row_condition!r}, "
            f"expected {condition!r} (from path {political_party}/{condition})"
        )


def _validate_expected_political_party(
    row_political_party: str, context: str, condition: str, political_party: str
) -> None:
    if row_political_party != political_party:
        raise AssertionError(
            f"{context}: column 'political_party' is {row_political_party!r}, "
            f"expected {political_party!r} (from path {political_party}/{condition})"
        )


def validate_assignments_file(
    csv_path: Path,
    ground_truth_post_pool: pd.DataFrame,
    *,
    political_party: str,
    condition: str,
    expected_row_count: int,
    config: MirrorViewConfig,
    coverage_tracker: AssignmentCoverageTracker | None = None,
) -> int:
    """Validate one assignments.csv file for expected schema and row invariants."""
    cell = _cell_label(political_party, condition)
    _validate_csv_file_exists(
        csv_path,
        political_party=political_party,
        condition=condition,
        config=config,
    )

    df = pd.read_csv(csv_path)

    _validate_no_missing_columns(
        df,
        political_party=political_party,
        condition=condition,
    )

    actual_row_count = len(df)
    if actual_row_count != expected_row_count:
        _log_fail(
            f"{cell}: row count",
            expected=str(expected_row_count),
            actual=str(actual_row_count),
        )
        raise AssertionError(
            f"{csv_path}: expected {expected_row_count} rows for configured cell "
            f"{cell}, got {actual_row_count}"
        )
    _log_pass(
        f"{cell}: row count",
        expected=str(expected_row_count),
        actual=str(actual_row_count),
    )

    for row_num, row in enumerate(df.itertuples(index=False, name=None), start=2):
        assignment_id, raw_post_ids, row_political_party, row_condition, _created_at = row
        context = f"{csv_path} row {row_num} ({assignment_id!r})"
        _validate_expected_condition(
            row_condition=row_condition,
            context=context,
            condition=condition,
            political_party=political_party,
        )
        _validate_expected_political_party(
            row_political_party=row_political_party,
            context=context,
            condition=condition,
            political_party=political_party,
        )
        post_ids = get_post_ids_list(raw_post_ids, context)
        if coverage_tracker is not None:
            coverage_tracker.record_assignment(post_ids)
        sampled = _get_ground_truth_sample_toxicity_political_stance(
            post_ids=post_ids,
            ground_truth_post_pool=ground_truth_post_pool,
            context=context,
        )

        total_left_leaning_posts = int((sampled["sampled_stance"] == "left").sum())
        total_right_leaning_posts = int((sampled["sampled_stance"] == "right").sum())
        oversample_left = _infer_oversample_left(
            total_left_leaning_posts, total_right_leaning_posts
        )
        pre._validate_assignment_invariants(sampled, oversample_left)

    return len(df)


def _validate_root_directory(series_root: Path) -> None:
    expected = f"directory at {series_root}"
    if series_root.is_dir():
        _log_pass("series_root", expected=expected, actual="directory")
        return
    if not series_root.exists():
        actual = "missing"
    elif series_root.is_file():
        actual = "file (not a directory)"
    else:
        actual = "not a directory"
    _log_fail("series_root", expected=expected, actual=actual)
    raise FileNotFoundError(f"Not a directory: {series_root}")


def _log_configured_cells(config: MirrorViewConfig) -> list[tuple[str, str, int]]:
    cells = list(config.iter_cells())
    expected = ", ".join(f"{party}/{condition} ({count} rows)" for party, condition, count in cells)
    _log_pass(
        f"config {config.name!r} cells",
        expected=expected,
        actual=f"{len(cells)} configured cells",
    )
    return cells


def validate_series_root(series_root: Path, config: MirrorViewConfig) -> None:
    """Validate all configured assignment CSVs under series_root; raises on first failure."""
    _validate_root_directory(series_root)

    input_posts_path = resolve_repo_path(config.input_posts_path)
    expected_ground_truth = f"readable CSV at {input_posts_path}"
    if not input_posts_path.is_file():
        _log_fail(
            "ground_truth_posts",
            expected=expected_ground_truth,
            actual="missing",
        )
        raise FileNotFoundError(f"Ground truth posts file not found: {input_posts_path}")
    ground_truth_post_pool = pd.read_csv(input_posts_path)
    ground_truth_post_pool = ground_truth_post_pool.set_index("post_primary_key")
    _log_pass(
        "ground_truth_posts",
        expected=expected_ground_truth,
        actual=f"{len(ground_truth_post_pool)} posts indexed by post_primary_key",
    )

    configured_cells = _log_configured_cells(config)
    coverage_tracker = _create_coverage_tracker_if_exists(config, ground_truth_post_pool)

    for political_party, condition, expected_row_count in configured_cells:
        csv_path = series_root / political_party / condition / OUTPUT_RECORDS_FILENAME
        validate_assignments_file(
            csv_path,
            ground_truth_post_pool,
            political_party=political_party,
            condition=condition,
            expected_row_count=expected_row_count,
            config=config,
            coverage_tracker=coverage_tracker,
        )

    if coverage_tracker is not None and config.expected_total_unique_posts is not None:
        _validate_unique_assigned_posts(
            coverage_tracker,
            expected_total_unique_posts=config.expected_total_unique_posts,
        )
    if coverage_tracker is not None and config.expected_min_assignments_per_post is not None:
        _validate_min_assignments_per_post(
            coverage_tracker,
            expected_min_assignments_per_post=config.expected_min_assignments_per_post,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate precomputed assignments.csv trees against MirrorView invariants."
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to MirrorView YAML config (e.g. jobs/mirrorview/config/default.yaml).",
    )
    parser.add_argument(
        "--path",
        required=True,
        help="Path to a precomputed series directory, relative to repo root "
        "(e.g. data/mirrorview/2026_04_03-05:34:59)",
    )
    args = parser.parse_args()
    config = load_mirrorview_config(args.config)
    series_root = (ROOT_DIR / args.path).resolve()
    validate_series_root(series_root, config)
    _log_pass(
        "validation complete",
        expected=f"all configured checks pass for {series_root}",
        actual="all checks passed",
    )


if __name__ == "__main__":
    main()

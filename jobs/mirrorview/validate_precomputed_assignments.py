"""Validate on-disk precomputed MirrorView assignment CSVs against precompute invariants.

Expects the same layout as `precompute_assignments.write_assignments`:
`<series_root>/{political_party}/{study_condition}/assignments.csv`
for the cartesian product of POLITICAL_PARTIES and STUDY_CONDITIONS.

Usage (from repo root):

    uv run python jobs/mirrorview/validate_precomputed_assignments.py \\
        --path data/mirrorview/2026_04_03-09:36:03
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import jobs.mirrorview.precompute_assignments as pre
from lib.constants import ROOT_DIR

_EXPECTED_ASSIGNMENT_COLUMNS = (
    "id",
    "assigned_post_ids",
    "political_party",
    "condition",
    "created_at",
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


def _validate_csv_file_exists(csv_path: Path) -> None:
    if not csv_path.is_file():
        raise FileNotFoundError(
            "Expected assignments file missing (layout must match "
            f"{pre.POLITICAL_PARTIES} x {pre.STUDY_CONDITIONS}): {csv_path}"
        )


def _validate_no_missing_columns(df: pd.DataFrame, csv_path: Path) -> None:
    missing = [c for c in _EXPECTED_ASSIGNMENT_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{csv_path}: missing columns {missing}")


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
) -> int:
    """Validate one assignments.csv file for expected schema and row invariants."""
    _validate_csv_file_exists(csv_path)

    df = pd.read_csv(csv_path)

    _validate_no_missing_columns(df, csv_path)

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
    if not series_root.is_dir():
        raise FileNotFoundError(f"Not a directory: {series_root}")


def validate_series_root(series_root: Path) -> None:
    """Validate all assignment CSVs under series_root; raises on first failure."""
    _validate_root_directory(series_root)

    # posts used to generate the assignments (these are the posts that will
    # actually be shown to participants)
    ground_truth_post_pool = pd.read_csv(pre.INPUT_POSTS_PATH)

    ground_truth_post_pool = ground_truth_post_pool.set_index("post_primary_key")

    for political_party in pre.POLITICAL_PARTIES:
        for condition in pre.STUDY_CONDITIONS:
            csv_path = series_root / political_party / condition / pre.OUTPUT_RECORDS_FILENAME
            n_rows = validate_assignments_file(
                csv_path,
                ground_truth_post_pool,
                political_party=political_party,
                condition=condition,
            )
            print(f"OK: {political_party}/{condition} ({n_rows} rows) -> {csv_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate precomputed assignments.csv trees against MirrorView invariants."
    )
    parser.add_argument(
        "--path",
        required=True,
        help="Path to a precomputed series directory, relative to repo root "
        "(e.g. data/mirrorview/2026_04_03-05:34:59)",
    )
    args = parser.parse_args()
    series_root = (ROOT_DIR / args.path).resolve()
    validate_series_root(series_root)
    print(f"All checks passed for {series_root}")


if __name__ == "__main__":
    main()

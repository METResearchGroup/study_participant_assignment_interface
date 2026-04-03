"""Validate on-disk precomputed MirrorView assignment CSVs against precompute invariants.

Expects the same layout as `precompute_assignments.write_assignments`:
`<series_root>/{political_party}/{study_condition}/assignments.csv`
for the cartesian product of POLITICAL_PARTIES and STUDY_CONDITIONS.

Usage (from repo root):

    uv run python jobs/mirrorview/validate_precomputed_assignments.py \\
        --path data/mirrorview/2026_04_03-05:34:59
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import jobs.mirrorview.precompute_assignments as pre  # noqa: E402

_EXPECTED_ASSIGNMENT_COLUMNS = ("id", "assigned_post_ids", "condition", "created_at")


def _infer_oversample_left(left_n: int, right_n: int) -> bool:
    if left_n == 11 and right_n == 9:
        return True
    if left_n == 10 and right_n == 10:
        return False
    raise AssertionError(
        "Left/right counts must be 11/9 (oversample left on high-toxicity) or 10/10 "
        f"(oversample right); got {left_n}/{right_n}"
    )


def _assigned_posts_to_sampled(
    post_ids: list[str],
    lookup: pd.DataFrame,
    *,
    context: str,
) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for pid in post_ids:
        if pid not in lookup.index:
            raise ValueError(f"{context}: unknown post_primary_key {pid!r}")
        row = lookup.loc[pid]
        rows.append(
            {
                "sample_toxicity_type": str(row["sample_toxicity_type"]),
                "sampled_stance": str(row["sampled_stance"]),
            }
        )
    return pd.DataFrame(rows)


def validate_series_root(series_root: Path) -> None:
    """Validate all assignment CSVs under series_root; raises on first failure."""
    if not series_root.is_dir():
        raise FileNotFoundError(f"Not a directory: {series_root}")

    input_posts = pd.read_csv(pre.INPUT_POSTS_PATH)
    if not input_posts["post_primary_key"].is_unique:
        raise ValueError("Input posts must have unique post_primary_key values")
    lookup = input_posts.set_index("post_primary_key")

    for political_party in pre.POLITICAL_PARTIES:
        for condition in pre.STUDY_CONDITIONS:
            csv_path = series_root / political_party / condition / pre.OUTPUT_RECORDS_FILENAME
            if not csv_path.is_file():
                raise FileNotFoundError(
                    "Expected assignments file missing (layout must match "
                    f"{pre.POLITICAL_PARTIES} × {pre.STUDY_CONDITIONS}): {csv_path}"
                )

            df = pd.read_csv(csv_path)
            missing = [c for c in _EXPECTED_ASSIGNMENT_COLUMNS if c not in df.columns]
            if missing:
                raise ValueError(f"{csv_path}: missing columns {missing}")

            for row_offset, (_, row) in enumerate(df.iterrows()):
                row_num = row_offset + 2  # 1-based sheet row, +1 for header
                context = f"{csv_path} row {row_num} ({row.get('id', '')!r})"
                if row["condition"] != condition:
                    raise AssertionError(
                        f"{context}: column 'condition' is {row['condition']!r}, "
                        f"expected {condition!r} (from path {political_party}/{condition})"
                    )
                raw_post_ids = row["assigned_post_ids"]
                post_ids = json.loads(str(raw_post_ids))
                if not isinstance(post_ids, list):
                    raise TypeError(f"{context}: assigned_post_ids must decode to a list")
                sampled = _assigned_posts_to_sampled(
                    [str(x) for x in post_ids], lookup, context=context
                )
                left_n = int((sampled["sampled_stance"] == "left").sum())
                right_n = int((sampled["sampled_stance"] == "right").sum())
                oversample_left = _infer_oversample_left(left_n, right_n)
                pre._validate_assignment_invariants(sampled, oversample_left)

            print(f"OK: {political_party}/{condition} ({len(df)} rows) -> {csv_path}")


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
    series_root = (_REPO_ROOT / args.path).resolve()
    validate_series_root(series_root)
    print(f"All checks passed for {series_root}")


if __name__ == "__main__":
    main()

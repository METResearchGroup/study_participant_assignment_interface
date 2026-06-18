"""Precompute the assignments for the MirrorView project.

Intended specs: https://docs.google.com/document/d/1A9kAlsCKgjk2qOlcJf_mriC7V9dbhn8VTT3Qb7HgDLc/edit?tab=t.0

Invariants mentioned in specs:

Every 20 posts:

- 5 low toxicity
- 5 high toxicity
- 10 middle toxicity

For toxicity, also split by left/right

- For low toxicity (5 posts): left 3 / right 2
- For high toxicity (5 posts): alternates 3/2 vs 2/3
- For middle toxicity (10 posts): split 5/5

Per-participant distribution with current logic:

- Toxicity: always ~5 / 5 / 10 (low/high/middle)
- Ideology: usually 10/10 or 11/9 (left/right)

Selection prioritizes: Unseen posts in that condition; so full coverage is achieved before repeats.
    - This point is natively addressed in the precomputation approach by randomly shuffling and
      selecting posts.
"""

from __future__ import annotations

import argparse
import json
import pathlib

import numpy as np
import pandas as pd

from jobs.mirrorview.config_loader import (
    MirrorViewConfig,
    load_mirrorview_config,
    resolve_repo_path,
)
from jobs.mirrorview.constants import OUTPUT_RECORDS_FILENAME
from jobs.mirrorview.generate_assignment_ids import generate_assignment_ids
from lib.timestamp_utils import get_current_timestamp

STANCES = ["left", "right"]
TOXICITY_LEVELS = ["sample_low_toxicity", "sample_middle_toxicity", "sample_high_toxicity"]
POST_CATEGORIES = [
    "left__sample_low_toxicity",
    "left__sample_high_toxicity",
    "left__sample_middle_toxicity",
    "right__sample_low_toxicity",
    "right__sample_high_toxicity",
    "right__sample_middle_toxicity",
]

TOTAL_POSTS_TO_ASSIGN = 20
TOTAL_LOW_TOXICITY_POSTS = 5
TOTAL_HIGH_TOXICITY_POSTS = 5
TOTAL_MIDDLE_TOXICITY_POSTS = 10
# Derived from fixed low (3L/2R) + middle (5L/5R) + high alternating (3L/2R vs 2L/3R).
VALID_LEFT_RIGHT_TOTALS = {
    "oversample_left": {"left": 11, "right": 9},
    "oversample_right": {"left": 10, "right": 10},
}


def load_input_posts(input_posts_path: pathlib.Path) -> pd.DataFrame:
    """Load the input posts from the CSV file."""
    return pd.read_csv(input_posts_path)


def write_assignments(
    assignments: pd.DataFrame,
    political_party: str,
    condition: str,
    *,
    output_records_root_prefix: pathlib.Path,
) -> None:
    output_path = output_records_root_prefix / political_party / condition / OUTPUT_RECORDS_FILENAME
    output_path.parent.mkdir(parents=True, exist_ok=True)
    assignments.to_csv(output_path, index=False)


def _validate_assignment_invariants(sampled: pd.DataFrame, oversample_left: bool) -> None:
    if len(sampled) != TOTAL_POSTS_TO_ASSIGN:
        raise AssertionError(f"Expected {TOTAL_POSTS_TO_ASSIGN} posts, got {len(sampled)}")

    # validate toxicity counts
    tox_col = sampled["sample_toxicity_type"]
    low = int((tox_col == "sample_low_toxicity").sum())
    high = int((tox_col == "sample_high_toxicity").sum())
    mid = int((tox_col == "sample_middle_toxicity").sum())
    exp_l, exp_h, exp_m = (
        TOTAL_LOW_TOXICITY_POSTS,
        TOTAL_HIGH_TOXICITY_POSTS,
        TOTAL_MIDDLE_TOXICITY_POSTS,
    )
    if low != exp_l or high != exp_h or mid != exp_m:
        raise AssertionError(
            "Toxicity counts expected low/mid/high = "
            f"{exp_l}/{exp_m}/{exp_h}, got {low}/{mid}/{high}"
        )

    # validate left/right counts
    left_n = int((sampled["sampled_stance"] == "left").sum())
    right_n = int((sampled["sampled_stance"] == "right").sum())
    key = "oversample_left" if oversample_left else "oversample_right"
    expected = VALID_LEFT_RIGHT_TOTALS[key]
    if left_n != expected["left"] or right_n != expected["right"]:
        raise AssertionError(
            f"Left/right counts for {key} expected {expected['left']}/{expected['right']}, "
            f"got {left_n}/{right_n}"
        )


def _sample_n_rows(df: pd.DataFrame, n: int, *, rng: np.random.Generator) -> pd.DataFrame:
    if len(df) < n:
        msg = f"Need at least {n} posts in this stance/toxicity bucket, found {len(df)}"
        raise ValueError(msg)
    return df.sample(n=n, random_state=rng).reset_index(drop=True)


def split_input_posts_by_stance_toxicity(
    input_posts: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Split posts into stance/toxicity buckets used for bundle sampling."""
    if "stance_toxicity_key" not in input_posts.columns:
        raise ValueError("input_posts must include a 'stance_toxicity_key' column")

    return {
        key: input_posts.loc[input_posts["stance_toxicity_key"] == key].reset_index(drop=True)
        for key in POST_CATEGORIES
    }


def _generate_one_assignment(
    splits: dict[str, pd.DataFrame],
    *,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Sample one valid 20-post bundle from pre-split stance/toxicity pools."""
    oversample_left = rng.random() < 0.5
    high_left_n = 3 if oversample_left else 2
    high_right_n = 2 if oversample_left else 3

    parts = [
        _sample_n_rows(df=splits["left__sample_low_toxicity"], n=3, rng=rng),
        _sample_n_rows(df=splits["right__sample_low_toxicity"], n=2, rng=rng),
        _sample_n_rows(df=splits["left__sample_middle_toxicity"], n=5, rng=rng),
        _sample_n_rows(df=splits["right__sample_middle_toxicity"], n=5, rng=rng),
        _sample_n_rows(df=splits["left__sample_high_toxicity"], n=high_left_n, rng=rng),
        _sample_n_rows(df=splits["right__sample_high_toxicity"], n=high_right_n, rng=rng),
    ]

    combined = pd.concat(parts, ignore_index=True)
    perm = rng.permutation(len(combined))
    combined = combined.iloc[perm].reset_index(drop=True)

    _validate_assignment_invariants(combined, oversample_left)

    return combined


def generate_precomputed_assignments(
    input_posts: pd.DataFrame,
    *,
    total_records_to_create: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    splits = split_input_posts_by_stance_toxicity(input_posts)

    assigned_post_ids: list[str] = []
    for i in range(total_records_to_create):
        if i % 100 == 0:
            print(f"Generated {i:04d}/{total_records_to_create:04d} assignments.")
        sampled = _generate_one_assignment(splits, rng=rng)
        post_ids = [str(primary_key) for primary_key in sampled["post_primary_key"].tolist()]
        assigned_post_ids.append(json.dumps(post_ids))

    return pd.DataFrame({"assigned_post_ids": assigned_post_ids})


def generate_and_export_precomputed_assignments(
    input_posts: pd.DataFrame,
    political_party: str,
    condition: str,
    *,
    assignments_per_cell: int,
    output_records_root_prefix: pathlib.Path,
    rng: np.random.Generator,
) -> None:
    """Build assignment rows for one party/condition cell and write assignments.csv."""
    precomputed_assignments = generate_precomputed_assignments(
        input_posts,
        total_records_to_create=assignments_per_cell,
        rng=rng,
    )
    created_at = get_current_timestamp()
    n = len(precomputed_assignments)
    exportable_assignments = pd.DataFrame(
        {
            "id": generate_assignment_ids(political_party, condition, n),
            "assigned_post_ids": precomputed_assignments["assigned_post_ids"],
            "political_party": political_party,
            "condition": condition,
            "created_at": created_at,
        }
    )
    write_assignments(
        assignments=exportable_assignments,
        political_party=political_party,
        condition=condition,
        output_records_root_prefix=output_records_root_prefix,
    )


def generate_and_export_all_precomputed_assignments(
    input_posts: pd.DataFrame,
    config: MirrorViewConfig,
    *,
    output_records_root_prefix: pathlib.Path,
    rng: np.random.Generator,
) -> None:
    """Export precomputed assignments for each configured party/condition cell."""
    for political_party, condition, assignments_per_cell in config.iter_cells():
        print(
            f"Generating precomputed assignments: political_party={political_party!r}, "
            f"condition={condition!r}"
        )
        generate_and_export_precomputed_assignments(
            input_posts=input_posts,
            political_party=political_party,
            condition=condition,
            assignments_per_cell=assignments_per_cell,
            output_records_root_prefix=output_records_root_prefix,
            rng=rng,
        )
        print(
            f"Finished precomputed assignments: political_party={political_party!r}, "
            f"condition={condition!r}."
        )


def main(config_path: pathlib.Path) -> None:
    config = load_mirrorview_config(config_path)
    input_posts_path = resolve_repo_path(config.input_posts_path)
    local_data_root = resolve_repo_path(config.local_data_dir)
    output_records_root_prefix = local_data_root / get_current_timestamp()
    rng = np.random.default_rng(config.random_seed)

    input_posts = load_input_posts(input_posts_path)
    input_posts["stance_toxicity_key"] = (
        input_posts["sampled_stance"] + "__" + input_posts["sample_toxicity_type"]
    )

    generate_and_export_all_precomputed_assignments(
        input_posts,
        config,
        output_records_root_prefix=output_records_root_prefix,
        rng=rng,
    )
    print(f"Wrote precomputed assignments under {output_records_root_prefix}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Precompute MirrorView assignment CSV batches.")
    parser.add_argument(
        "--config",
        required=True,
        type=pathlib.Path,
        help="Path to MirrorView YAML config (e.g. jobs/mirrorview/config/default.yaml).",
    )
    cli_args = parser.parse_args()
    main(cli_args.config)

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

import json
import pathlib

import numpy as np
import pandas as pd

from jobs.mirrorview.constants import LOCAL_DATA_PREFIX, OUTPUT_RECORDS_FILENAME
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
POLITICAL_PARTIES = ["democrat", "republican"]
STUDY_CONDITIONS = ["control", "training", "training_assisted"]

# Single generator for the whole batch run so draws are reproducible for a given seed.
RANDOM_SEED = 42
RNG = np.random.default_rng(RANDOM_SEED)

TOTAL_POSTS_TO_ASSIGN = 20
TOTAL_LOW_TOXICITY_POSTS = 5
TOTAL_HIGH_TOXICITY_POSTS = 5
TOTAL_MIDDLE_TOXICITY_POSTS = 10
# Derived from fixed low (3L/2R) + middle (5L/5R) + high alternating (3L/2R vs 2L/3R).
VALID_LEFT_RIGHT_TOTALS = {
    "oversample_left": {"left": 11, "right": 9},
    "oversample_right": {"left": 10, "right": 10},
}

CURRENT_DIR = pathlib.Path(__file__).parent
INPUT_POSTS_FILENAME = "all_mirrors_claude.csv"
INPUT_POSTS_PATH = CURRENT_DIR / INPUT_POSTS_FILENAME

TOTAL_RECORDS_TO_CREATE = 1000
OUTPUT_RECORDS_ROOT_PREFIX = LOCAL_DATA_PREFIX / get_current_timestamp()


def load_input_posts() -> pd.DataFrame:
    """Load the input posts from the CSV file."""
    df = pd.read_csv(INPUT_POSTS_PATH)
    return df


def write_assignments(
    assignments: pd.DataFrame,
    political_party: str,
    condition: str,
) -> None:
    output_path = OUTPUT_RECORDS_ROOT_PREFIX / political_party / condition / OUTPUT_RECORDS_FILENAME
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


def _sample_n_rows(df: pd.DataFrame, n: int) -> pd.DataFrame:
    if len(df) < n:
        msg = f"Need at least {n} posts in this stance/toxicity bucket, found {len(df)}"
        raise ValueError(msg)
    return df.sample(n=n, random_state=RNG).reset_index(drop=True)


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


def _generate_one_assignment(splits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Sample one valid 20-post bundle from pre-split stance/toxicity pools.

    Draws counts per the MirrorView spec (low/middle/high and left/right splits),
    shuffles row order, validates invariants, and returns the combined frame.
    """
    oversample_left = RNG.random() < 0.5
    high_left_n = 3 if oversample_left else 2
    high_right_n = 2 if oversample_left else 3

    # get samples from each subset
    parts = [
        _sample_n_rows(df=splits["left__sample_low_toxicity"], n=3),
        _sample_n_rows(df=splits["right__sample_low_toxicity"], n=2),
        _sample_n_rows(df=splits["left__sample_middle_toxicity"], n=5),
        _sample_n_rows(df=splits["right__sample_middle_toxicity"], n=5),
        _sample_n_rows(df=splits["left__sample_high_toxicity"], n=high_left_n),
        _sample_n_rows(df=splits["right__sample_high_toxicity"], n=high_right_n),
    ]

    # combine results and shuffle
    combined = pd.concat(parts, ignore_index=True)
    perm = RNG.permutation(len(combined))
    combined = combined.iloc[perm].reset_index(drop=True)

    # validate invariants
    _validate_assignment_invariants(combined, oversample_left)

    return combined


def generate_precomputed_assignments(input_posts: pd.DataFrame) -> pd.DataFrame:
    """Algorithm:

    Split `input_posts` into six subsets:

    LOW_TOXIC_LEFT = df[df["stance_toxicity_key"] == "left__sample_low_toxicity"]
    LOW_TOXIC_RIGHT = ...
    MIDDLE_TOXIC_LEFT = ...
    MIDDLE_TOXIC_RIGHT = ...
    HIGH_TOXIC_LEFT = ...
    HIGH_TOXIC_RIGHT = ...

    Then randomly select `n` samples for each. Also set a boolean,
    oversample_left, with p=0.5 of True

    SUBSET_LOW_TOXIC_LEFT = pick 3 from LOW_TOXIC_LEFT
    SUBSET_LOW_TOXIC_RIGHT = pick 2 from LOW_TOXIC_RIGHT
    SUBSET_MIDDLE_TOXIC_LEFT = (randomly pick 5 from MIDDLE_TOXIC_LEFT)
    SUBSET_MIDDLE_TOXIC_RIGHT = (randomly pick 5 from MIDDLE_TOXIC_RIGHT)
    SUBSET_HIGH_TOXIC_LEFT = (randomly pick 3 from HIGH_TOXIC_LEFT if oversample_left, else 2)
    SUBSET_HIGH_TOXIC_RIGHT = (randomly pick 2 from HIGH_TOXIC_RIGHT if oversample_left, else 3)

    Then create the sample

    sampled_df = []

    Then validate against the invariants.
    - TOTAL_POSTS_TO_ASSIGN
    - TOTAL_LOW_TOXICITY_POSTS
    - TOTAL_HIGH_TOXICITY_POSTS
    - TOTAL_MIDDLE_TOXICITY_POSTS
    - VALID_LEFT_RIGHT_TOTALS

    The naive approach of randomly sampling posts until we meet all the invariants
    is (1) tricky to validate and (2) possibly an O(N) while-loop.

    In contrast, here the rate-limiting step is however long it takes to split
    the posts into the subsets, as the sampling operation is O(N//d), where d=6
    is the number of subsets and each of the d=6 sampling operations is a linear
    operation on an average of N//d rows. This eliminates the while-loop and
    makes sampling more consistent and well defined and removes the invariant
    checks required from a naive while-loop.

    It's OK to sample with replacement. It'll be a pain to make sure that we
    implement sampling without replacement, and since we include randomness,
    then in expectation this'll lead to a balanced representation.
    """
    splits = split_input_posts_by_stance_toxicity(input_posts)

    assigned_post_ids: list[str] = []
    for i in range(TOTAL_RECORDS_TO_CREATE):
        if i % 100 == 0:
            print(f"Generated {i:04d}/{TOTAL_RECORDS_TO_CREATE:04d} assignments.")
        sampled = _generate_one_assignment(splits)
        post_ids = [str(primary_key) for primary_key in sampled["post_primary_key"].tolist()]
        assigned_post_ids.append(json.dumps(post_ids))

    return pd.DataFrame({"assigned_post_ids": assigned_post_ids})


def generate_and_export_precomputed_assignments(
    input_posts: pd.DataFrame, political_party: str, condition: str
) -> None:
    """Build assignment rows for one party/condition cell and write assignments.csv."""
    precomputed_assignments = generate_precomputed_assignments(input_posts)
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
        assignments=exportable_assignments, political_party=political_party, condition=condition
    )


def generate_and_export_all_precomputed_assignments(input_posts: pd.DataFrame) -> None:
    """Export precomputed assignments for each political party and study condition.

    Writes one assignments.csv per (POLITICAL_PARTIES x STUDY_CONDITIONS) cell.
    """
    for political_party in POLITICAL_PARTIES:
        for condition in STUDY_CONDITIONS:
            print(
                f"Generating precomputed assignments: political_party={political_party!r}, "
                f"condition={condition!r}"
            )
            generate_and_export_precomputed_assignments(
                input_posts=input_posts, political_party=political_party, condition=condition
            )
            print(
                f"Finished precomputed assignments: political_party={political_party!r}, "
                f"condition={condition!r}."
            )


def main():
    # load input posts
    input_posts: pd.DataFrame = load_input_posts()

    # add key used in precomputation sampling.
    input_posts["stance_toxicity_key"] = (
        input_posts["sampled_stance"] + "__" + input_posts["sample_toxicity_type"]
    )

    # run and export precomputation
    generate_and_export_all_precomputed_assignments(input_posts)


if __name__ == "__main__":
    main()

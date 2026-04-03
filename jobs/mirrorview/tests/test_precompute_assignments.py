"""Unit tests for jobs.mirrorview.precompute_assignments."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

import jobs.mirrorview.precompute_assignments as pa


def _row(
    post_primary_key: str,
    stance: str,
    tox: str,
    stance_toxicity_key: str | None = None,
) -> dict[str, str]:
    if stance_toxicity_key is None:
        stance_toxicity_key = f"{stance}__{tox}"
    return {
        "post_primary_key": post_primary_key,
        "sampled_stance": stance,
        "sample_toxicity_type": tox,
        "stance_toxicity_key": stance_toxicity_key,
    }


def minimal_input_posts(rows_per_bucket: int = 5) -> pd.DataFrame:
    """Enough rows per stance×toxicity bucket for sampling (max draw 5 per bucket)."""
    rows: list[dict[str, str]] = []
    pk_i = 0
    for key in pa.POST_CATEGORIES:
        stance, tox_type = key.split("__", 1)
        for _ in range(rows_per_bucket):
            rows.append(
                _row(f"pk_{pk_i}", stance, tox_type, stance_toxicity_key=key),
            )
            pk_i += 1
    return pd.DataFrame(rows)


def _oversample_left_frame() -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for i in range(3):
        rows.append(_row(f"ll{i}", "left", "sample_low_toxicity"))
    for i in range(2):
        rows.append(_row(f"lr{i}", "right", "sample_low_toxicity"))
    for i in range(5):
        rows.append(_row(f"ml{i}", "left", "sample_middle_toxicity"))
    for i in range(5):
        rows.append(_row(f"mr{i}", "right", "sample_middle_toxicity"))
    for i in range(3):
        rows.append(_row(f"hl{i}", "left", "sample_high_toxicity"))
    for i in range(2):
        rows.append(_row(f"hr{i}", "right", "sample_high_toxicity"))
    return pd.DataFrame(rows)


def _oversample_right_frame() -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for i in range(3):
        rows.append(_row(f"ll{i}", "left", "sample_low_toxicity"))
    for i in range(2):
        rows.append(_row(f"lr{i}", "right", "sample_low_toxicity"))
    for i in range(5):
        rows.append(_row(f"ml{i}", "left", "sample_middle_toxicity"))
    for i in range(5):
        rows.append(_row(f"mr{i}", "right", "sample_middle_toxicity"))
    for i in range(2):
        rows.append(_row(f"hl{i}", "left", "sample_high_toxicity"))
    for i in range(3):
        rows.append(_row(f"hr{i}", "right", "sample_high_toxicity"))
    return pd.DataFrame(rows)


def _infer_oversample_left_from_counts(result: pd.DataFrame) -> bool:
    counts = result.groupby("stance_toxicity_key", observed=True).size()
    counts_by_key: dict[str, int] = counts.to_dict()
    left_high = counts_by_key.get("left__sample_high_toxicity", 0)
    right_high = counts_by_key.get("right__sample_high_toxicity", 0)
    if left_high == 3 and right_high == 2:
        return True
    if left_high == 2 and right_high == 3:
        return False
    raise AssertionError(
        "Unexpected high-toxicity split; expected left/right of 3/2 or 2/3, "
        f"got {left_high}/{right_high}"
    )


class TestValidateAssignmentInvariants:
    """Tests for _validate_assignment_invariants function."""

    def test_passes_for_valid_oversample_left_bundle(self):
        """11L/9R with 5/5/10 toxicity counts matches oversample_left=True."""
        frame = _oversample_left_frame()
        pa._validate_assignment_invariants(frame, True)

    def test_passes_for_valid_oversample_right_bundle(self):
        """10L/10R with high 2L/3R matches oversample_left=False."""
        frame = _oversample_right_frame()
        pa._validate_assignment_invariants(frame, False)

    @pytest.mark.parametrize("bad_len", [19, 21])
    def test_raises_when_row_count_not_twenty(self, bad_len: int):
        """Bundle must contain exactly TOTAL_POSTS_TO_ASSIGN posts."""
        rows = [_row(f"p{i}", "left", "sample_low_toxicity") for i in range(bad_len)]
        frame = pd.DataFrame(rows)
        with pytest.raises(AssertionError, match="Expected 20"):
            pa._validate_assignment_invariants(frame, True)

    @pytest.mark.parametrize(
        "low,mid,high",
        [
            (4, 10, 6),
            (6, 10, 4),
            (5, 9, 6),
            (5, 11, 4),
        ],
    )
    def test_raises_on_wrong_toxicity_counts(self, low: int, mid: int, high: int):
        """Low, middle, and high toxicity row counts must be 5, 10, and 5."""
        rows: list[dict[str, str]] = []
        rows.extend(_row(f"l{i}", "left", "sample_low_toxicity") for i in range(low))
        rows.extend(_row(f"m{i}", "left", "sample_middle_toxicity") for i in range(mid))
        rows.extend(_row(f"h{i}", "left", "sample_high_toxicity") for i in range(high))
        assert len(rows) == 20
        frame = pd.DataFrame(rows)
        with pytest.raises(AssertionError, match="Toxicity counts"):
            pa._validate_assignment_invariants(frame, True)

    def test_raises_on_wrong_left_right_for_oversample_left(self):
        """10L/10R cannot satisfy oversample_left=True (expects 11/9)."""
        frame = _oversample_right_frame()
        with pytest.raises(AssertionError, match="Left/right"):
            pa._validate_assignment_invariants(frame, True)

    def test_raises_on_wrong_left_right_for_oversample_right(self):
        """11L/9R cannot satisfy oversample_left=False (expects 10/10)."""
        frame = _oversample_left_frame()
        with pytest.raises(AssertionError, match="Left/right"):
            pa._validate_assignment_invariants(frame, False)


class TestGenerateOneAssignment:
    """Tests for _generate_one_assignment function."""

    def test_returns_twenty_rows_and_valid_invariants(self):
        """Sampled bundle has 20 rows and satisfies invariants for the returned flag."""
        posts = minimal_input_posts(5)
        splits = pa.split_input_posts_by_stance_toxicity(posts)
        result = pa._generate_one_assignment(splits)
        oversample_left = _infer_oversample_left_from_counts(result)
        assert len(result) == 20
        pa._validate_assignment_invariants(result, oversample_left)

    def test_bucket_counts_match_spec(self):
        """Per-bucket stance_toxicity_key counts follow low/mid/high draws."""
        posts = minimal_input_posts(5)
        splits = pa.split_input_posts_by_stance_toxicity(posts)
        result = pa._generate_one_assignment(splits)
        counts = result.groupby("stance_toxicity_key", observed=True).size()
        for key in pa.POST_CATEGORIES:
            assert key in counts.index
        assert counts["left__sample_low_toxicity"] == 3
        assert counts["right__sample_low_toxicity"] == 2
        assert counts["left__sample_middle_toxicity"] == 5
        assert counts["right__sample_middle_toxicity"] == 5
        if _infer_oversample_left_from_counts(result):
            assert counts["left__sample_high_toxicity"] == 3
            assert counts["right__sample_high_toxicity"] == 2
        else:
            assert counts["left__sample_high_toxicity"] == 2
            assert counts["right__sample_high_toxicity"] == 3

    def test_raises_when_pool_too_small(self):
        """Undersized pool raises ValueError mentioning bucket size."""
        posts = minimal_input_posts(1)
        splits = pa.split_input_posts_by_stance_toxicity(posts)
        with pytest.raises(ValueError, match="at least 3"):
            pa._generate_one_assignment(splits)

    def test_no_duplicate_primary_keys_within_bundle(self):
        """A bundle never contains the same post_primary_key twice."""
        posts = minimal_input_posts(5)
        splits = pa.split_input_posts_by_stance_toxicity(posts)
        result = pa._generate_one_assignment(splits)
        keys = result["post_primary_key"].tolist()
        assert len(keys) == len(set(keys))


class TestGeneratePrecomputedAssignments:
    """Tests for generate_precomputed_assignments function."""

    def test_output_has_total_records_to_create_rows(self):
        """Output row count matches TOTAL_RECORDS_TO_CREATE."""
        posts = minimal_input_posts(5)
        with patch.object(pa, "TOTAL_RECORDS_TO_CREATE", 3):
            result = pa.generate_precomputed_assignments(posts)
        assert len(result) == 3

    def test_assigned_post_ids_is_valid_json_list_of_twenty(self):
        """Each cell is JSON array of 20 string post IDs."""
        posts = minimal_input_posts(5)
        with patch.object(pa, "TOTAL_RECORDS_TO_CREATE", 2):
            result = pa.generate_precomputed_assignments(posts)
        for cell in result["assigned_post_ids"]:
            parsed = json.loads(cell)
            assert isinstance(parsed, list)
            assert len(parsed) == 20
            assert all(isinstance(x, str) for x in parsed)

    def test_each_bundle_satisfies_invariants_when_joined_to_posts(self):
        """Re-hydrating rows from input reproduces valid bundles."""
        posts = minimal_input_posts(5)
        with patch.object(pa, "TOTAL_RECORDS_TO_CREATE", 4):
            out = pa.generate_precomputed_assignments(posts)
        for raw_ids in out["assigned_post_ids"]:
            ids = json.loads(raw_ids)
            subset = posts.loc[posts["post_primary_key"].isin(ids)].copy()
            subset = subset.drop_duplicates(subset="post_primary_key").reset_index(drop=True)
            assert len(subset) == 20
            left_n = int((subset["sampled_stance"] == "left").sum())
            if left_n == 11:
                flag = True
            elif left_n == 10:
                flag = False
            else:
                pytest.fail(f"unexpected left count {left_n}")
            pa._validate_assignment_invariants(subset, flag)

    def test_raises_when_stance_toxicity_key_missing(self):
        """Missing stance_toxicity_key must error before sampling."""
        posts = minimal_input_posts(5).drop(columns=["stance_toxicity_key"])
        with pytest.raises(ValueError, match="stance_toxicity_key"):
            pa.generate_precomputed_assignments(posts)

    def test_oversample_left_rate_near_half_over_many_draws(self):
        """Bernoulli oversample should not be stuck always True/False."""
        posts = minimal_input_posts(5)
        splits = pa.split_input_posts_by_stance_toxicity(posts)
        pa.RNG = np.random.default_rng(pa.RANDOM_SEED)
        n = 400
        n_left = sum(
            _infer_oversample_left_from_counts(pa._generate_one_assignment(splits))
            for _ in range(n)
        )
        assert 120 < n_left < 280


class TestWriteAssignments:
    """Tests for write_assignments function."""

    def test_writes_csv_to_expected_path(self, tmp_path):
        """CSV is written under OUTPUT path with expected columns."""
        out_root = tmp_path / "mirror_batch"
        frame = pd.DataFrame(
            {
                "id": ["democrat-control-0001"],
                "assigned_post_ids": [json.dumps(["a", "b"])],
                "condition": ["control"],
                "created_at": ["ts"],
            }
        )
        with patch.object(pa, "OUTPUT_RECORDS_ROOT_PREFIX", out_root):
            pa.write_assignments(frame, "democrat", "control")
        csv_path = out_root / "democrat" / "control" / pa.OUTPUT_RECORDS_FILENAME
        assert csv_path.is_file()
        loaded = pd.read_csv(csv_path)
        expected_cols = {"id", "assigned_post_ids", "condition", "created_at"}
        assert set(loaded.columns) == expected_cols

    def test_creates_parent_directories(self, tmp_path):
        """Nested party/condition directories are created."""
        out_root = tmp_path / "nested"
        frame = pd.DataFrame(
            {
                "id": ["x"],
                "assigned_post_ids": [json.dumps([])],
                "condition": ["control"],
                "created_at": ["t"],
            }
        )
        with patch.object(pa, "OUTPUT_RECORDS_ROOT_PREFIX", out_root):
            pa.write_assignments(frame, "republican", "training_assisted")
        assert (out_root / "republican" / "training_assisted").is_dir()


class TestGenerateAndExportPrecomputedAssignments:
    """Tests for generate_and_export_precomputed_assignments function."""

    def test_composes_ids_and_condition_and_timestamp(self):
        """Export builds stable id column and passes frame to write_assignments."""
        posts = minimal_input_posts(5)
        base = pd.DataFrame(
            {
                "assigned_post_ids": [json.dumps(["p1"]), json.dumps(["p2"])],
            }
        )
        mock_write = MagicMock()
        with (
            patch.object(pa, "generate_precomputed_assignments", return_value=base),
            patch.object(pa, "get_current_timestamp", return_value="fixed_ts"),
            patch.object(pa, "write_assignments", mock_write),
        ):
            pa.generate_and_export_precomputed_assignments(posts, "democrat", "control")
        mock_write.assert_called_once()
        call_kw = mock_write.call_args.kwargs
        assignments = call_kw["assignments"]
        expected_ids = ["democrat-control-0001", "democrat-control-0002"]
        assert assignments["id"].tolist() == expected_ids
        assert assignments["condition"].tolist() == ["control", "control"]
        assert assignments["created_at"].tolist() == ["fixed_ts", "fixed_ts"]
        assert mock_write.call_args.kwargs["political_party"] == "democrat"
        assert mock_write.call_args.kwargs["condition"] == "control"


class TestGenerateAndExportAllPrecomputedAssignments:
    """Tests for generate_and_export_all_precomputed_assignments function."""

    def test_iterates_cartesian_product_of_constants(self):
        """Each party×condition pair is exported exactly once."""
        posts = minimal_input_posts(3)
        mock_export = MagicMock()
        with patch.object(pa, "generate_and_export_precomputed_assignments", mock_export):
            pa.generate_and_export_all_precomputed_assignments(posts)
        expected_calls = len(pa.POLITICAL_PARTIES) * len(pa.STUDY_CONDITIONS)
        assert mock_export.call_count == expected_calls
        seen: set[tuple[str, str]] = set()
        for c in mock_export.call_args_list:
            kw = c.kwargs
            seen.add((kw["political_party"], kw["condition"]))
        assert seen == {(p, cond) for p in pa.POLITICAL_PARTIES for cond in pa.STUDY_CONDITIONS}

"""Unit tests for lambdas.get_study_assignment.handler.

Run:
    PYTHONPATH=. uv run pytest lambdas/get_study_assignment/tests/test_handler.py
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import lambdas.get_study_assignment.handler as h
from jobs.mirrorview.config_loader import load_mirrorview_config
from lib.constants import ROOT_DIR
from lib.dynamodb import (
    AssignmentCounterConflictError,
    UserAssignmentPayload,
    UserAssignmentRecord,
)

DEFAULT_CONFIG = load_mirrorview_config(ROOT_DIR / "jobs/mirrorview/config/default.yaml")
DEFAULT_STUDY_CONDITIONS = DEFAULT_CONFIG.configured_conditions()
SCALED_CONFIG = load_mirrorview_config(ROOT_DIR / "jobs/mirrorview/config/mirrorview_scaled.yaml")
BATCH_PREFIX = "precomputed_assignments/2026_06_10-15:00:00"
BATCH_URI = f"s3://{DEFAULT_CONFIG.s3.bucket}/{BATCH_PREFIX}"


def _make_payload(
    *,
    s3_bucket: str = "bucket",
    s3_key: str = "precomputed_assignments/democrat/control/assignments.csv",
    assignment_id: str = "democrat-control-0001",
    metadata: str | None = None,
) -> UserAssignmentPayload:
    metadata_value = metadata or json.dumps({"political_party": "democrat", "condition": "control"})
    return UserAssignmentPayload(
        s3_bucket=s3_bucket,
        s3_key=s3_key,
        assignment_id=assignment_id,
        metadata=metadata_value,
    )


def _make_record(
    *,
    user_id: str = "user-1",
    payload: UserAssignmentPayload | None = None,
) -> UserAssignmentRecord:
    payload_value = payload or _make_payload()
    return UserAssignmentRecord(
        study_id="study-1",
        study_iteration_id="iter-1",
        user_id=user_id,
        iteration_user_key=f"iter-1#{user_id}",
        payload=payload_value,
        created_at="2026-01-01T00:00:00",
    )


class TestGetUserAssignmentRecordIfExists:
    """Tests for get_user_assignment_record_if_exists function."""

    def test_get_user_assignment_record_if_exists_returns_none(self):
        """Test returns None when no user assignment exists in storage."""
        # Arrange
        with patch.object(h, "get_user_assignment", return_value=None) as mock_get:
            # Act
            result = h.get_user_assignment_record_if_exists(
                study_id="study-1",
                study_iteration_id="iter-1",
                prolific_id="prolific-1",
            )

        # Assert
        assert result is None
        mock_get.assert_called_once_with(
            study_id="study-1",
            study_iteration_id="iter-1",
            user_id="prolific-1",
            table_name=h.user_assignments_table_name,
            region_name=h.region_name,
        )

    def test_get_user_assignment_record_if_exists_returns_record(self):
        """Test returns the exact record object when assignment exists."""
        # Arrange
        expected = _make_record(user_id="prolific-2")
        with patch.object(h, "get_user_assignment", return_value=expected) as mock_get:
            # Act
            result = h.get_user_assignment_record_if_exists(
                study_id="study-2",
                study_iteration_id="iter-2",
                prolific_id="prolific-2",
            )

        # Assert
        assert result == expected
        mock_get.assert_called_once()


class TestSelectLeastAssignmentPartyConditionKey:
    """Tests for select_least_assignment_party_condition_key function."""

    def test_select_least_key_prefers_smaller_counter(self):
        """Test selection prefers lower counter for requested party."""
        # Arrange
        records = [
            MagicMock(study_unique_assignment_key="democrat:control", counter=5),
            MagicMock(study_unique_assignment_key="democrat:training", counter=5),
            MagicMock(study_unique_assignment_key="democrat:training_assisted", counter=2),
        ]
        with patch.object(h, "list_assignment_counters_for_party", return_value=records):
            # Act
            result = h.select_least_assignment_party_condition_key(
                study_id="study-1",
                study_iteration_id="iter-1",
                political_party="democrat",
                study_conditions=DEFAULT_STUDY_CONDITIONS,
            )

        # Assert
        expected = ("democrat:training_assisted", 2)
        assert result == expected

    def test_select_least_key_tie_breaks_by_key_name(self):
        """Test ties resolve deterministically by lexical key ordering."""
        # Arrange
        records = [
            MagicMock(study_unique_assignment_key="democrat:training_assisted", counter=3),
            MagicMock(study_unique_assignment_key="democrat:control", counter=3),
            MagicMock(study_unique_assignment_key="democrat:training", counter=3),
        ]
        with patch.object(h, "list_assignment_counters_for_party", return_value=records):
            # Act
            result = h.select_least_assignment_party_condition_key(
                study_id="study-1",
                study_iteration_id="iter-1",
                political_party="democrat",
                study_conditions=DEFAULT_STUDY_CONDITIONS,
            )

        # Assert
        expected = ("democrat:control", 3)
        assert result == expected

    def test_select_least_key_adds_missing_default_conditions_with_zero(self):
        """Test missing default conditions are considered with implicit zero counter."""
        # Arrange
        records = [MagicMock(study_unique_assignment_key="democrat:control", counter=4)]
        with patch.object(h, "list_assignment_counters_for_party", return_value=records):
            # Act
            result = h.select_least_assignment_party_condition_key(
                study_id="study-1",
                study_iteration_id="iter-1",
                political_party="democrat",
                study_conditions=DEFAULT_STUDY_CONDITIONS,
            )

        # Assert
        expected = ("democrat:training", 0)
        assert result == expected

    def test_select_least_key_filters_non_matching_party_keys(self):
        """Test keys not matching the requested party are ignored."""
        # Arrange
        records = [
            MagicMock(study_unique_assignment_key="democrat:control", counter=8),
            MagicMock(study_unique_assignment_key="democrat:training", counter=5),
            MagicMock(study_unique_assignment_key="democrat:training_assisted", counter=1),
            MagicMock(study_unique_assignment_key="republican:control", counter=1),
            MagicMock(study_unique_assignment_key="republican:training", counter=1),
            MagicMock(study_unique_assignment_key="republican:training_assisted", counter=1),
        ]
        with patch.object(h, "list_assignment_counters_for_party", return_value=records):
            # Act
            result = h.select_least_assignment_party_condition_key(
                study_id="study-1",
                study_iteration_id="iter-1",
                political_party="democrat",
                study_conditions=DEFAULT_STUDY_CONDITIONS,
            )

        # Assert
        expected = ("democrat:training_assisted", 1)
        assert result == expected

    def test_select_least_key_raises_when_no_candidates(self):
        """Test defensive error when no counters and no default conditions exist."""
        # Arrange
        with patch.object(h, "list_assignment_counters_for_party", return_value=[]):
            # Act / Assert
            with pytest.raises(ValueError, match="No candidate assignment keys"):
                h.select_least_assignment_party_condition_key(
                    study_id="study-1",
                    study_iteration_id="iter-1",
                    political_party="democrat",
                    study_conditions=(),
                )


class TestAssignUserToCondition:
    """Tests for assign_user_to_condition function."""

    def test_assign_user_to_condition_success_first_try(self):
        """Test successful assignment and counter increment on first attempt."""
        # Arrange
        with (
            patch.object(
                h,
                "select_least_assignment_party_condition_key",
                return_value=("democrat:control", 7),
            ) as mock_select,
            patch.object(
                h, "compare_and_increment_assignment_counter", return_value=8
            ) as mock_increment,
        ):
            # Act
            result = h.assign_user_to_condition(
                study_id="study-1",
                study_iteration_id="iter-1",
                political_party="democrat",
                study_conditions=DEFAULT_STUDY_CONDITIONS,
            )

        # Assert
        expected = {"condition": "control", "total_in_condition": 8}
        assert result == expected
        mock_select.assert_called_once_with(
            study_id="study-1",
            study_iteration_id="iter-1",
            political_party="democrat",
            study_conditions=DEFAULT_STUDY_CONDITIONS,
        )
        mock_increment.assert_called_once_with(
            study_id="study-1",
            study_iteration_id="iter-1",
            study_unique_assignment_key="democrat:control",
            expected_counter=7,
            table_name=h.study_assignment_counter_table_name,
            region_name=h.region_name,
        )

    def test_assign_user_to_condition_retries_on_conflict_then_succeeds(self):
        """Test retries continue after conflict and return first successful result."""
        # Arrange
        with (
            patch.object(
                h,
                "select_least_assignment_party_condition_key",
                return_value=("democrat:training_assisted", 2),
            ) as mock_select,
            patch.object(
                h,
                "compare_and_increment_assignment_counter",
                side_effect=[AssignmentCounterConflictError("race"), 3],
            ) as mock_increment,
        ):
            # Act
            result = h.assign_user_to_condition(
                study_id="study-1",
                study_iteration_id="iter-1",
                political_party="democrat",
                study_conditions=DEFAULT_STUDY_CONDITIONS,
            )

        # Assert
        expected = {"condition": "training_assisted", "total_in_condition": 3}
        assert result == expected
        assert mock_select.call_count == 2
        assert mock_increment.call_count == 2

    def test_assign_user_to_condition_raises_after_max_retries(self):
        """Test function raises RuntimeError when all retries conflict."""
        # Arrange
        with (
            patch.object(h, "MAX_ASSIGNMENT_RETRIES", 3),
            patch.object(
                h,
                "select_least_assignment_party_condition_key",
                return_value=("democrat:control", 0),
            ),
            patch.object(
                h,
                "compare_and_increment_assignment_counter",
                side_effect=AssignmentCounterConflictError("still racing"),
            ),
        ):
            # Act / Assert
            with pytest.raises(RuntimeError, match="Failed to assign user after 3 retries"):
                h.assign_user_to_condition(
                    study_id="study-1",
                    study_iteration_id="iter-1",
                    political_party="democrat",
                    study_conditions=DEFAULT_STUDY_CONDITIONS,
                )


class TestBuildPrecomputedAssignmentsS3Key:
    """Tests for build_precomputed_assignments_s3_key function."""

    def test_builds_key_from_batch_prefix_party_and_condition(self):
        result = h.build_precomputed_assignments_s3_key(
            batch_key_prefix=BATCH_PREFIX,
            political_party="democrat",
            condition="control",
        )
        expected = f"{BATCH_PREFIX}/democrat/control/assignments.csv"
        assert result == expected


class TestSelectLeastAssignmentScaledConfig:
    """Tests for one-condition scaled assignment behavior."""

    def test_scaled_config_only_considers_training_assisted(self):
        records = [MagicMock(study_unique_assignment_key="democrat:training_assisted", counter=2)]
        with patch.object(h, "list_assignment_counters_for_party", return_value=records):
            result = h.select_least_assignment_party_condition_key(
                study_id="study-1",
                study_iteration_id="iter-1",
                political_party="democrat",
                study_conditions=SCALED_CONFIG.configured_conditions(),
            )
        assert result == ("democrat:training_assisted", 2)


class TestSetUserAssignmentRecord:
    """Tests for set_user_assignment_record function."""

    def test_set_user_assignment_record_persists_expected_payload(self):
        """Test payload includes assignment id, metadata, and batch S3 key."""
        persisted_record = _make_record(user_id="prolific-1")
        with (
            patch.object(
                h,
                "assign_user_to_condition",
                return_value={"condition": "control", "total_in_condition": 11},
            ) as mock_assign,
            patch.object(
                h, "generate_single_assignment_id", return_value="democrat-control-0011"
            ) as mock_id,
            patch.object(h, "put_user_assignment", return_value=persisted_record) as mock_put,
        ):
            result = h.set_user_assignment_record(
                study_id="study-1",
                study_iteration_id="iter-1",
                prolific_id="prolific-1",
                political_party="democrat",
                mirrorview_config=DEFAULT_CONFIG,
                batch_key_prefix=BATCH_PREFIX,
            )

        assert result == persisted_record
        mock_assign.assert_called_once_with(
            study_id="study-1",
            study_iteration_id="iter-1",
            political_party="democrat",
            study_conditions=DEFAULT_STUDY_CONDITIONS,
        )
        mock_id.assert_called_once_with(
            political_party="democrat",
            condition="control",
            index=11,
        )

        mock_put.assert_called_once()
        call_kwargs = mock_put.call_args.kwargs
        payload = call_kwargs["payload"]
        assert isinstance(payload, UserAssignmentPayload)
        assert payload.s3_bucket == DEFAULT_CONFIG.s3.bucket
        assert payload.s3_key == f"{BATCH_PREFIX}/democrat/control/assignments.csv"
        assert payload.assignment_id == "democrat-control-0011"
        assert json.loads(payload.metadata) == {
            "political_party": "democrat",
            "condition": "control",
        }

    def test_set_user_assignment_record_raises_on_non_positive_total_in_condition(self):
        """Test invalid counter value prevents assignment id generation and write."""
        # Arrange
        with patch.object(
            h,
            "assign_user_to_condition",
            return_value={"condition": "control", "total_in_condition": 0},
        ):
            # Act / Assert
            with pytest.raises(ValueError, match="Invalid counter for assignment generation"):
                h.set_user_assignment_record(
                    study_id="study-1",
                    study_iteration_id="iter-1",
                    prolific_id="prolific-1",
                    political_party="democrat",
                    mirrorview_config=DEFAULT_CONFIG,
                    batch_key_prefix=BATCH_PREFIX,
                )


class TestGetOrSetUserAssignmentRecord:
    """Tests for get_or_set_user_assignment_record function."""

    def test_get_or_set_user_assignment_record_returns_existing(self):
        """Test existing assignment is returned and set path is skipped."""
        # Arrange
        existing = _make_record(user_id="prolific-1")
        with (
            patch.object(
                h, "get_user_assignment_record_if_exists", return_value=existing
            ) as mock_get,
            patch.object(h, "set_user_assignment_record") as mock_set,
        ):
            # Act
            result = h.get_or_set_user_assignment_record(
                study_id="study-1",
                study_iteration_id="iter-1",
                prolific_id="prolific-1",
                political_party="democrat",
                mirrorview_config=DEFAULT_CONFIG,
                batch_key_prefix=BATCH_PREFIX,
            )

        # Assert
        assert result == existing
        mock_get.assert_called_once_with(
            study_id="study-1",
            study_iteration_id="iter-1",
            prolific_id="prolific-1",
        )
        mock_set.assert_not_called()

    def test_get_or_set_user_assignment_record_sets_when_missing(self):
        """Test missing assignment triggers creation and returns new record."""
        # Arrange
        created = _make_record(user_id="prolific-2")
        with (
            patch.object(h, "get_user_assignment_record_if_exists", return_value=None) as mock_get,
            patch.object(h, "set_user_assignment_record", return_value=created) as mock_set,
        ):
            # Act
            result = h.get_or_set_user_assignment_record(
                study_id="study-2",
                study_iteration_id="iter-2",
                prolific_id="prolific-2",
                political_party="republican",
                mirrorview_config=DEFAULT_CONFIG,
                batch_key_prefix=BATCH_PREFIX,
            )

        # Assert
        assert result == created
        mock_get.assert_called_once()
        mock_set.assert_called_once_with(
            study_id="study-2",
            study_iteration_id="iter-2",
            prolific_id="prolific-2",
            political_party="republican",
            mirrorview_config=DEFAULT_CONFIG,
            batch_key_prefix=BATCH_PREFIX,
        )


class TestLoadPrecomputedAssignments:
    """Tests for load_precomputed_assignments function."""

    def test_load_precomputed_assignments_delegates_to_s3_loader(self):
        expected = pd.DataFrame({"id": ["x"], "assigned_post_ids": ['["p1"]']})
        with patch.object(h.S3, "load_csv_to_dataframe", return_value=expected) as mock_loader:
            result = h.load_precomputed_assignments(
                bucket="example-bucket",
                s3_key="some/key/assignments.csv",
            )

        assert result is expected
        mock_loader.assert_called_once_with(key="some/key/assignments.csv")


class TestGetPrecomputedAssignment:
    """Tests for get_precomputed_assignment function."""

    def test_get_precomputed_assignment_parses_json_string_payload(self):
        """Test JSON string assigned_post_ids is deserialized into list."""
        # Arrange
        record = _make_record(user_id="prolific-1")
        payload = _make_payload(assignment_id="democrat-control-0007")
        frame = pd.DataFrame([{"id": "democrat-control-0007", "assigned_post_ids": '["p1", "p2"]'}])
        with patch.object(h, "load_precomputed_assignments", return_value=frame):
            # Act
            result = h.get_precomputed_assignment(record, payload)

        # Assert
        expected = ["p1", "p2"]
        assert result == expected

    def test_get_precomputed_assignment_accepts_list_payload(self):
        """Test list assigned_post_ids is returned without transformation."""
        # Arrange
        record = _make_record(user_id="prolific-2")
        payload = _make_payload(assignment_id="democrat-control-0010")
        frame = pd.DataFrame([{"id": "democrat-control-0010", "assigned_post_ids": ["p3", "p4"]}])
        with patch.object(h, "load_precomputed_assignments", return_value=frame):
            # Act
            result = h.get_precomputed_assignment(record, payload)

        # Assert
        expected = ["p3", "p4"]
        assert result == expected

    def test_get_precomputed_assignment_raises_when_assignment_missing(self):
        """Test missing assignment id in CSV raises ValueError."""
        # Arrange
        record = _make_record(user_id="prolific-3")
        payload = _make_payload(assignment_id="missing-id")
        frame = pd.DataFrame([{"id": "other-id", "assigned_post_ids": '["p1"]'}])
        with patch.object(h, "load_precomputed_assignments", return_value=frame):
            # Act / Assert
            with pytest.raises(ValueError, match="Assignment not found for user"):
                h.get_precomputed_assignment(record, payload)

    def test_get_precomputed_assignment_raises_on_unexpected_payload_type(self):
        """Test unsupported assigned_post_ids type raises explicit ValueError."""
        # Arrange
        record = _make_record(user_id="prolific-4")
        payload = _make_payload(assignment_id="democrat-control-0011")
        frame = pd.DataFrame(
            [{"id": "democrat-control-0011", "assigned_post_ids": {"bad": "type"}}]
        )
        with patch.object(h, "load_precomputed_assignments", return_value=frame):
            # Act / Assert
            with pytest.raises(ValueError, match="Unexpected assigned_post_ids format"):
                h.get_precomputed_assignment(record, payload)

    def test_get_precomputed_assignment_raises_when_json_decodes_to_non_list(self):
        """Test JSON string that decodes to a non-list raises ValueError."""
        record = _make_record(user_id="prolific-5")
        payload = _make_payload(assignment_id="democrat-control-0012")
        frame = pd.DataFrame(
            [{"id": "democrat-control-0012", "assigned_post_ids": '{"not": "a list"}'}]
        )
        with patch.object(h, "load_precomputed_assignments", return_value=frame):
            with pytest.raises(ValueError, match="must be a JSON list"):
                h.get_precomputed_assignment(record, payload)

    def test_get_precomputed_assignment_raises_when_list_elements_not_strings(self):
        """Test list or JSON list with non-str elements raises ValueError."""
        record = _make_record(user_id="prolific-6")
        payload = _make_payload(assignment_id="democrat-control-0013")
        frame = pd.DataFrame([{"id": "democrat-control-0013", "assigned_post_ids": [1, 2, 3]}])
        with patch.object(h, "load_precomputed_assignments", return_value=frame):
            with pytest.raises(ValueError, match="list of strings"):
                h.get_precomputed_assignment(record, payload)

        frame_json = pd.DataFrame([{"id": "democrat-control-0013", "assigned_post_ids": "[1, 2]"}])
        with patch.object(h, "load_precomputed_assignments", return_value=frame_json):
            with pytest.raises(ValueError, match="list of strings"):
                h.get_precomputed_assignment(record, payload)


class TestHandler:
    """Tests for handler function."""

    def test_handler_forwards_event_fields_to_main(self):
        """Test handler maps event fields into main kwargs and returns its output."""
        # Arrange
        event = {
            "study_id": "study-1",
            "study_iteration_id": "iter-1",
            "prolific_id": "prolific-1",
            "political_party": "democrat",
            "assignment_batch_uri": BATCH_URI,
        }
        expected = {"assigned_post_ids": ["p1"], "already_assigned": True, "condition": "control"}
        with patch.object(h, "main", return_value=expected) as mock_main:
            # Act
            result = h.handler(event, context=None)

        # Assert
        assert result == expected
        mock_main.assert_called_once_with(
            study_id="study-1",
            study_iteration_id="iter-1",
            prolific_id="prolific-1",
            political_party="democrat",
            assignment_batch_uri=BATCH_URI,
        )

    def test_handler_raises_key_error_on_missing_assignment_batch_uri(self):
        event = {
            "study_id": "study-1",
            "study_iteration_id": "iter-1",
            "prolific_id": "prolific-1",
            "political_party": "democrat",
        }

        with pytest.raises(KeyError, match="assignment_batch_uri"):
            h.handler(event, context=None)

    def test_main_raises_when_config_bucket_mismatches_uri(self):
        mismatched_config = DEFAULT_CONFIG.model_copy(deep=True)
        mismatched_config.s3.bucket = "other-bucket"
        with (
            patch.object(
                h,
                "parse_assignment_batch_uri",
                return_value=(DEFAULT_CONFIG.s3.bucket, BATCH_PREFIX),
            ),
            patch.object(h, "load_batch_config", return_value=mismatched_config),
        ):
            with pytest.raises(ValueError, match="bucket"):
                h.main(
                    study_id="study-1",
                    study_iteration_id="iter-1",
                    prolific_id="prolific-1",
                    political_party="democrat",
                    assignment_batch_uri=BATCH_URI,
                )

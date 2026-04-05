"""Unit tests for jobs.mirrorview.generate_assignment_ids.

Can be run with:
PYTHONPATH=. uv run pytest jobs/mirrorview/tests/test_generate_assignment_ids.py
"""

from __future__ import annotations

import pytest

import jobs.mirrorview.generate_assignment_ids as g


class TestGenerateSingleAssignmentId:
    """Tests for generate_single_assignment_id function."""

    def test_formats_party_condition_and_zero_padded_index(self):
        """Test id is party-condition-index with index zero-padded to width 4."""
        # Arrange
        political_party = "democrat"
        condition = "control"
        index = 7

        # Act
        result = g.generate_single_assignment_id(
            political_party=political_party,
            condition=condition,
            index=index,
        )

        # Assert
        expected = "democrat-control-0007"
        assert result == expected

    def test_index_zero_uses_four_digit_suffix(self):
        """Test index 0 maps to -0000 suffix."""
        # Arrange
        political_party = "republican"
        condition = "training_assisted"
        index = 0

        # Act
        result = g.generate_single_assignment_id(
            political_party=political_party,
            condition=condition,
            index=index,
        )

        # Assert
        expected = "republican-training_assisted-0000"
        assert result == expected

    @pytest.mark.parametrize(
        "index,expected",
        [
            (10, "democrat-control-0010"),
            (100, "democrat-control-0100"),
            (999, "democrat-control-0999"),
        ],
    )
    def test_zero_padding_examples_at_ten_hundred_and_999(self, index: int, expected: str):
        """Show how ids look at index 10, 100, and 999 (four-digit suffix)."""
        # Arrange
        political_party = "democrat"
        condition = "control"

        # Act
        result = g.generate_single_assignment_id(
            political_party=political_party,
            condition=condition,
            index=index,
        )

        # Assert
        assert result == expected

    def test_index_wider_than_four_digits_is_not_truncated(self):
        """Test indices beyond 9999 still appear fully (min width 4, not max)."""
        # Arrange
        political_party = "democrat"
        condition = "control"
        index = 10000

        # Act
        result = g.generate_single_assignment_id(
            political_party=political_party,
            condition=condition,
            index=index,
        )

        # Assert
        expected = "democrat-control-10000"
        assert result == expected


class TestGenerateAssignmentIds:
    """Tests for generate_assignment_ids function."""

    def test_empty_list_when_total_assignments_zero(self):
        """Test no ids when total_assignments is 0."""
        # Arrange
        total_assignments = 0

        # Act
        result = g.generate_assignment_ids(
            political_party="democrat",
            condition="control",
            total_assignments=total_assignments,
        )

        # Assert
        expected: list[str] = []
        assert result == expected

    def test_returns_sequential_ids_from_zero(self):
        """Test ids use indices 0 .. total_assignments-1 in order."""
        # Arrange
        political_party = "democrat"
        condition = "control"
        total_assignments = 3

        # Act
        result = g.generate_assignment_ids(
            political_party=political_party,
            condition=condition,
            total_assignments=total_assignments,
        )

        # Assert
        expected = [
            "democrat-control-0000",
            "democrat-control-0001",
            "democrat-control-0002",
        ]
        assert result == expected

    def test_each_element_uses_given_party_and_condition(self):
        """Test party and condition strings are applied to every generated id."""
        # Arrange
        political_party = "republican"
        condition = "training_assisted"
        total_assignments = 2

        # Act
        result = g.generate_assignment_ids(
            political_party=political_party,
            condition=condition,
            total_assignments=total_assignments,
        )

        # Assert
        expected = [
            "republican-training_assisted-0000",
            "republican-training_assisted-0001",
        ]
        assert result == expected

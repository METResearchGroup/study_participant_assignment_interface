"""DynamoDB smoke tests for assignment counters and user assignments.

Run:
    PYTHONPATH=. AWS_REGION=us-east-2 USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
    STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
    uv run python infra/tests/dynamodb_e2e_tests.py
"""

from __future__ import annotations

import json
import os
import traceback
import uuid
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from jobs.mirrorview.constants import DEFAULT_BUCKET, DEFAULT_S3_PREFIX, OUTPUT_RECORDS_FILENAME
from jobs.mirrorview.generate_assignment_ids import generate_single_assignment_id
from lib.dynamodb import (
    AssignmentCounterConflictError,
    UserAssignmentPayload,
    _build_iteration_assignment_key,
    compare_and_increment_assignment_counter,
    get_user_assignment,
    increment_assignment_counter,
    list_assignment_counters_for_party,
    put_user_assignment,
)
from lib.timestamp_utils import get_current_timestamp

TEST_ENV_PREFIX = "dev"


def _require_env(name: str) -> str:
    """Return a required env var or raise with a clear message."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _short_uuid() -> str:
    """Return a short, stable-for-logging UUID suffix."""
    return uuid.uuid4().hex[:8]


def _assert_equal(actual, expected, message: str) -> None:
    """Raise AssertionError with a consistent message on mismatch."""
    if actual != expected:
        raise AssertionError(f"{message}. Expected {expected}, got {actual}")


class DynamoDbSmokeTestBase:
    def setup(self) -> None:
        """Initialize env, IDs, and DynamoDB table handles for the test."""
        self.region_name = _require_env("AWS_REGION")
        self.user_assignments_table_name = _require_env("USER_ASSIGNMENTS_TABLE_NAME")
        self.assignment_counter_table_name = _require_env("STUDY_ASSIGNMENT_COUNTER_TABLE_NAME")

        self.study_id = f"study-{uuid.uuid4().hex}"
        self.study_iteration_id = f"{TEST_ENV_PREFIX}_{get_current_timestamp()}_{_short_uuid()}"

        dynamodb: Any = boto3.resource("dynamodb", region_name=self.region_name)
        self.user_assignments_table = dynamodb.Table(self.user_assignments_table_name)
        self.assignment_counter_table = dynamodb.Table(self.assignment_counter_table_name)

    def teardown(self) -> None:
        """Remove any rows created for this test iteration."""
        if not hasattr(self, "assignment_counter_table"):
            return
        self._cleanup_counter_rows_for_iteration()
        self._cleanup_user_assignments_for_iteration()

    def _assignment_key(self, political_party: str, condition: str) -> str:
        """Build a unique per-test assignment key using party + condition."""
        return f"{political_party}:{condition}-{_short_uuid()}"

    def _seed_counter_row(self, *, study_unique_assignment_key: str, counter: int) -> None:
        """Insert a deterministic counter row for a known starting state."""
        iteration_assignment_key = _build_iteration_assignment_key(
            self.study_iteration_id, study_unique_assignment_key
        )
        timestamp = get_current_timestamp()
        item = {
            "study_id": self.study_id,
            "iteration_assignment_key": iteration_assignment_key,
            "study_iteration_id": self.study_iteration_id,
            "study_unique_assignment_key": study_unique_assignment_key,
            "counter": counter,
            "created_at": timestamp,
            "last_updated_at": timestamp,
        }
        self.assignment_counter_table.put_item(Item=item)

    def _cleanup_counter_rows_for_iteration(self) -> None:
        """Delete counter rows matching the iteration key prefix."""
        prefix = f"{self.study_iteration_id}#"
        items = self._query_items(
            self.assignment_counter_table,
            sort_key="iteration_assignment_key",
            sort_prefix=prefix,
        )
        self._delete_items(
            self.assignment_counter_table,
            items,
            key_fields=("study_id", "iteration_assignment_key"),
        )

    def _cleanup_user_assignments_for_iteration(self) -> None:
        """Delete user assignment rows matching the iteration key prefix."""
        prefix = f"{self.study_iteration_id}#"
        items = self._query_items(
            self.user_assignments_table,
            sort_key="iteration_user_key",
            sort_prefix=prefix,
        )
        self._delete_items(
            self.user_assignments_table,
            items,
            key_fields=("study_id", "iteration_user_key"),
        )

    def _query_items(self, table, *, sort_key: str, sort_prefix: str) -> list[dict]:
        """Query all items for (study_id, sort_key begins_with prefix).

        Algorithm:
        1. Execute a KeyConditionExpression on the partition key (study_id) with a
           begins_with condition on the sort key.
        2. Paginate with LastEvaluatedKey until no more pages remain.
        3. Accumulate and return all items.
        """
        items: list[dict] = []
        last_key = None
        key_condition = Key("study_id").eq(self.study_id) & Key(sort_key).begins_with(sort_prefix)
        while True:
            query_kwargs = {"KeyConditionExpression": key_condition}
            if last_key:
                query_kwargs["ExclusiveStartKey"] = last_key
            response = table.query(**query_kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
        return items

    def _delete_items(self, table, items: Iterable[dict], *, key_fields: tuple[str, str]) -> None:
        """Batch delete items using the provided key fields."""
        with table.batch_writer() as batch:
            for item in items:
                key = {field: item[field] for field in key_fields}
                batch.delete_item(Key=key)


class TestUserAssignmentSmoke(DynamoDbSmokeTestBase):
    """Smoke tests for user assignment read/write round-trips."""

    def test_put_and_get_user_assignment(self) -> None:
        """Round-trip user assignment payload storage and retrieval."""
        # Arrange
        user_id = f"user-{uuid.uuid4().hex}"
        political_party = "democrat"
        condition = "control"
        payload_data = {
            "s3_bucket": DEFAULT_BUCKET,
            "s3_key": (
                f"{DEFAULT_S3_PREFIX}/{political_party}/{condition}/{OUTPUT_RECORDS_FILENAME}"
            ),
            "assignment_id": generate_single_assignment_id(
                political_party=political_party,
                condition=condition,
                index=1,
            ),
            "metadata": json.dumps({"political_party": political_party, "condition": condition}),
        }
        payload_model = UserAssignmentPayload.model_validate(payload_data)

        # Act
        stored = put_user_assignment(
            study_id=self.study_id,
            study_iteration_id=self.study_iteration_id,
            user_id=user_id,
            payload=payload_model,
            table_name=self.user_assignments_table_name,
            region_name=self.region_name,
        )
        fetched = get_user_assignment(
            study_id=self.study_id,
            study_iteration_id=self.study_iteration_id,
            user_id=user_id,
            table_name=self.user_assignments_table_name,
            region_name=self.region_name,
        )

        # Assert
        if fetched is None:
            raise AssertionError("get_user_assignment returned None after put_user_assignment")
        _assert_equal(fetched.study_id, stored.study_id, "Study ID mismatch")
        _assert_equal(
            fetched.study_iteration_id,
            stored.study_iteration_id,
            "study_iteration_id mismatch",
        )
        _assert_equal(fetched.user_id, stored.user_id, "User ID mismatch")
        expected_iteration_user_key = f"{stored.study_iteration_id}#{stored.user_id}"
        _assert_equal(
            fetched.iteration_user_key,
            expected_iteration_user_key,
            "iteration_user_key must match study_iteration_id#user_id",
        )
        _assert_equal(
            fetched.payload.model_dump(),
            stored.payload.model_dump(),
            "Payload mismatch",
        )


class TestIncrementAssignmentCounterSmoke(DynamoDbSmokeTestBase):
    """Smoke tests for increment-on-miss and increment sequencing."""

    def test_first_increment_returns_one(self) -> None:
        """First increment on a missing key returns 1."""
        # Arrange
        study_unique_assignment_key = self._assignment_key("democrat", "control")

        # Act
        first_counter = increment_assignment_counter(
            study_id=self.study_id,
            study_iteration_id=self.study_iteration_id,
            study_unique_assignment_key=study_unique_assignment_key,
            table_name=self.assignment_counter_table_name,
            region_name=self.region_name,
        )

        # Assert
        _assert_equal(first_counter, 1, "First counter increment should return 1")

    def test_repeated_increment_returns_next_value(self) -> None:
        """Sequential increments return increasing counter values."""
        # Arrange
        study_unique_assignment_key = self._assignment_key("democrat", "training_assisted")

        # Act
        first_counter = increment_assignment_counter(
            study_id=self.study_id,
            study_iteration_id=self.study_iteration_id,
            study_unique_assignment_key=study_unique_assignment_key,
            table_name=self.assignment_counter_table_name,
            region_name=self.region_name,
        )
        second_counter = increment_assignment_counter(
            study_id=self.study_id,
            study_iteration_id=self.study_iteration_id,
            study_unique_assignment_key=study_unique_assignment_key,
            table_name=self.assignment_counter_table_name,
            region_name=self.region_name,
        )

        # Assert
        _assert_equal(first_counter, 1, "First counter increment should return 1")
        _assert_equal(second_counter, 2, "Second increment should return 2")

    def test_concurrent_increment_uniqueness(self) -> None:
        """Concurrent increments return a distinct sequential set."""
        # Arrange
        study_unique_assignment_key = self._assignment_key("republican", "control")

        # Act
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(
                    increment_assignment_counter,
                    study_id=self.study_id,
                    study_iteration_id=self.study_iteration_id,
                    study_unique_assignment_key=study_unique_assignment_key,
                    table_name=self.assignment_counter_table_name,
                    region_name=self.region_name,
                )
                for _ in range(5)
            ]
            results = [future.result() for future in futures]

        # Assert
        sorted_results = sorted(results)
        _assert_equal(
            sorted_results,
            list(range(1, 6)),
            "Concurrent counter values should be sequential and distinct",
        )


class TestListAssignmentCountersForPartySmoke(DynamoDbSmokeTestBase):
    """Smoke tests for party-based counter listing and filtering."""

    def test_list_filters_by_party_prefix(self) -> None:
        """Listing returns only counters for the requested party."""
        # Arrange
        democrat_key_1 = self._assignment_key("democrat", "control")
        democrat_key_2 = self._assignment_key("democrat", "training_assisted")
        republican_key = self._assignment_key("republican", "control")
        self._seed_counter_row(study_unique_assignment_key=democrat_key_1, counter=2)
        self._seed_counter_row(study_unique_assignment_key=democrat_key_2, counter=5)
        self._seed_counter_row(study_unique_assignment_key=republican_key, counter=3)

        # Act
        records = list_assignment_counters_for_party(
            study_id=self.study_id,
            study_iteration_id=self.study_iteration_id,
            political_party="democrat",
            table_name=self.assignment_counter_table_name,
            region_name=self.region_name,
        )

        # Assert
        _assert_equal(len(records), 2, "Expected only democrat counters")
        counters_by_key = {record.study_unique_assignment_key: record.counter for record in records}
        _assert_equal(counters_by_key[democrat_key_1], 2, "Democrat control counter mismatch")
        _assert_equal(counters_by_key[democrat_key_2], 5, "Democrat training counter mismatch")
        if any("republican:" in record.study_unique_assignment_key for record in records):
            raise AssertionError("List should exclude counters for other parties")


class TestCompareAndIncrementAssignmentCounterSmoke(DynamoDbSmokeTestBase):
    """Smoke tests for compare-and-increment conflict and success paths."""

    def test_compare_and_increment_on_missing(self) -> None:
        """Compare-and-increment on missing row with expected 0 returns 1.

        This is expected for cases where we haven't created that row
        yet (e.g., the first time that the combination of party x condition
        is seen). We want the DynamoDB logic to handle this case for us rather
        than requiring a manual setup script."""
        # Arrange
        study_unique_assignment_key = self._assignment_key("democrat", "control")

        # Act
        counter = compare_and_increment_assignment_counter(
            study_id=self.study_id,
            study_iteration_id=self.study_iteration_id,
            study_unique_assignment_key=study_unique_assignment_key,
            expected_counter=0,
            table_name=self.assignment_counter_table_name,
            region_name=self.region_name,
        )

        # Assert
        _assert_equal(counter, 1, "Compare-and-increment should return 1")

    def test_compare_and_increment_conflict_raises(self) -> None:
        """Stale expected counter raises AssignmentCounterConflictError."""
        # Arrange
        study_unique_assignment_key = self._assignment_key("republican", "training_assisted")
        self._seed_counter_row(study_unique_assignment_key=study_unique_assignment_key, counter=2)

        # Act / Assert
        try:
            compare_and_increment_assignment_counter(
                study_id=self.study_id,
                study_iteration_id=self.study_iteration_id,
                study_unique_assignment_key=study_unique_assignment_key,
                expected_counter=1,
                table_name=self.assignment_counter_table_name,
                region_name=self.region_name,
            )
        except AssignmentCounterConflictError:
            return
        raise AssertionError("Expected AssignmentCounterConflictError for stale counter")

    def test_compare_and_increment_after_refresh(self) -> None:
        """Fresh expected counter increments successfully."""
        # Arrange
        study_unique_assignment_key = self._assignment_key("democrat", "training_assisted")
        self._seed_counter_row(study_unique_assignment_key=study_unique_assignment_key, counter=3)

        # Act
        counter = compare_and_increment_assignment_counter(
            study_id=self.study_id,
            study_iteration_id=self.study_iteration_id,
            study_unique_assignment_key=study_unique_assignment_key,
            expected_counter=3,
            table_name=self.assignment_counter_table_name,
            region_name=self.region_name,
        )

        # Assert
        _assert_equal(counter, 4, "Compare-and-increment should return 4")


TEST_CLASSES = [
    TestUserAssignmentSmoke,
    TestIncrementAssignmentCounterSmoke,
    TestListAssignmentCountersForPartySmoke,
    TestCompareAndIncrementAssignmentCounterSmoke,
]


def _iter_test_methods(test_instance) -> list[str]:
    """Return sorted test method names for a test instance."""
    methods = [
        name
        for name in dir(test_instance)
        if name.startswith("test_") and callable(getattr(test_instance, name))
    ]
    return sorted(methods)


def run_smoke_tests() -> int:
    """Run all smoke tests with setup/teardown and aggregated reporting.

    Algorithm:
    1. For each test class, instantiate it and discover `test_*` methods.
    2. For each method, run `setup()` -> test method -> `teardown()` in a
       try/finally block so cleanup runs even on failure.
    3. Track failures by fully qualified name and print a summary.
    """
    failed: set[str] = set()
    total_methods = sum(len(_iter_test_methods(cls())) for cls in TEST_CLASSES)
    for test_class in TEST_CLASSES:
        test_instance = test_class()
        for method_name in _iter_test_methods(test_instance):
            test_label = f"{test_class.__name__}.{method_name}"
            try:
                test_instance.setup()
                getattr(test_instance, method_name)()
                print(f"PASS {test_label}")
            except Exception as exc:
                failed.add(test_label)
                print(f"FAIL {test_label}: {exc}")
                traceback.print_exc()
            finally:
                try:
                    test_instance.teardown()
                except Exception as exc:
                    failed.add(test_label)
                    print(f"FAIL {test_label} (teardown): {exc}")
                    traceback.print_exc()

    passed_count = total_methods - len(failed)
    print(f"Summary: {passed_count} passed, {len(failed)} failed")
    return 1 if failed else 0


def main() -> None:
    """Entry point for manual execution."""
    raise SystemExit(run_smoke_tests())


if __name__ == "__main__":
    main()

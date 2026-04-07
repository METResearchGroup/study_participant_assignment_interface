"""Shared smoke suite for get_study_assignment across invocation backends."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from typing import Any

import boto3
import pandas as pd
from boto3.dynamodb.conditions import Key

from jobs.mirrorview.constants import DEFAULT_BUCKET, DEFAULT_S3_PREFIX, OUTPUT_RECORDS_FILENAME
from jobs.mirrorview.generate_assignment_ids import generate_single_assignment_id
from lambdas.get_study_assignment.smoke_tests.handler_invokers import HandlerInvoker
from lib.s3 import S3
from lib.testing_utils import _assert_equal, _require_env
from lib.timestamp_utils import get_current_timestamp

TEST_ENV_PREFIX = "local-smoke"


class HandlerSmokeTestBase:
    INVOKER: HandlerInvoker | None = None

    def __init__(self) -> None:
        if self.INVOKER is None:
            raise ValueError("Handler smoke suite requires INVOKER to be configured")
        self._invoker = self.INVOKER

    def setup(self) -> None:
        self.region_name = _require_env("AWS_REGION")
        self.user_assignments_table_name = _require_env("USER_ASSIGNMENTS_TABLE_NAME")
        self.assignment_counter_table_name = _require_env("STUDY_ASSIGNMENT_COUNTER_TABLE_NAME")

        self.study_id = f"study-{uuid.uuid4().hex}"
        self.study_iteration_id = (
            f"{TEST_ENV_PREFIX}_{get_current_timestamp()}_{uuid.uuid4().hex[:8]}"
        )

        dynamodb: Any = boto3.resource("dynamodb", region_name=self.region_name)
        self.user_assignments_table = dynamodb.Table(self.user_assignments_table_name)
        self.assignment_counter_table = dynamodb.Table(self.assignment_counter_table_name)
        self.s3_client: Any = boto3.client("s3", region_name=self.region_name)
        self.s3_store = S3(bucket=DEFAULT_BUCKET, region_name=self.region_name)
        self.created_s3_keys: set[str] = set()

    def teardown(self) -> None:
        if not hasattr(self, "assignment_counter_table"):
            return
        self._cleanup_counter_rows_for_iteration()
        self._cleanup_user_assignments_for_iteration()
        self._cleanup_s3_fixture_objects()

    def invoke_handler(self, event: dict[str, str]) -> dict[str, Any]:
        return self._invoker.invoke(event)

    def _make_event(self, *, prolific_id: str, political_party: str) -> dict[str, str]:
        return {
            "study_id": self.study_id,
            "study_iteration_id": self.study_iteration_id,
            "prolific_id": prolific_id,
            "political_party": political_party,
        }

    def _seed_precomputed_csv(
        self,
        *,
        political_party: str,
        condition: str,
        total_rows: int = 3,
    ) -> str:
        records = []
        for index in range(1, total_rows + 1):
            assignment_id = generate_single_assignment_id(
                political_party=political_party,
                condition=condition,
                index=index,
            )
            records.append(
                {
                    "id": assignment_id,
                    "assigned_post_ids": json.dumps(
                        [
                            f"{political_party}-{condition}-post-{index}-a",
                            f"{political_party}-{condition}-post-{index}-b",
                        ]
                    ),
                }
            )

        key = (
            f"{DEFAULT_S3_PREFIX}/~handler-smoke/{self.study_iteration_id}/"
            f"{political_party}/{condition}/{OUTPUT_RECORDS_FILENAME}"
        )
        csv_bytes = pd.DataFrame(records).to_csv(index=False).encode("utf-8")
        self.s3_store.upload_bytes(key=key, body=csv_bytes, content_type="text/csv")
        self.created_s3_keys.add(key)
        return key

    def _seed_party_condition_fixtures(self, political_party: str) -> dict[str, str]:
        return {
            "control": self._seed_precomputed_csv(
                political_party=political_party,
                condition="control",
            ),
            "training": self._seed_precomputed_csv(
                political_party=political_party,
                condition="training",
            ),
            "training_assisted": self._seed_precomputed_csv(
                political_party=political_party,
                condition="training_assisted",
            ),
        }

    def _query_items(self, table, *, sort_key: str, sort_prefix: str) -> list[dict]:
        items: list[dict] = []
        last_key = None
        key_condition = Key("study_id").eq(self.study_id) & Key(sort_key).begins_with(sort_prefix)
        while True:
            query_kwargs = {
                "KeyConditionExpression": key_condition,
                "ConsistentRead": True,
            }
            if last_key:
                query_kwargs["ExclusiveStartKey"] = last_key
            response = table.query(**query_kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
        return items

    def _query_user_assignments_for_iteration(self) -> list[dict]:
        return self._query_items(
            self.user_assignments_table,
            sort_key="iteration_user_key",
            sort_prefix=f"{self.study_iteration_id}#",
        )

    def _query_counters_for_iteration(self) -> list[dict]:
        return self._query_items(
            self.assignment_counter_table,
            sort_key="iteration_assignment_key",
            sort_prefix=f"{self.study_iteration_id}#",
        )

    def _delete_items(self, table, items: Iterable[dict], *, key_fields: tuple[str, str]) -> None:
        with table.batch_writer() as batch:
            for item in items:
                key = {field: item[field] for field in key_fields}
                batch.delete_item(Key=key)

    def _cleanup_user_assignments_for_iteration(self) -> None:
        items = self._query_user_assignments_for_iteration()
        self._delete_items(
            self.user_assignments_table,
            items,
            key_fields=("study_id", "iteration_user_key"),
        )

    def _cleanup_counter_rows_for_iteration(self) -> None:
        items = self._query_counters_for_iteration()
        self._delete_items(
            self.assignment_counter_table,
            items,
            key_fields=("study_id", "iteration_assignment_key"),
        )

    def _cleanup_s3_fixture_objects(self) -> None:
        for key in sorted(self.created_s3_keys):
            self.s3_client.delete_object(Bucket=DEFAULT_BUCKET, Key=key)


class TestHandlerSmokeSuite(HandlerSmokeTestBase):
    def test_new_user_happy_path(self) -> None:
        """End-to-end path for a **new participant** with no prior user assignment row."""
        self._seed_party_condition_fixtures("democrat")
        event = self._make_event(prolific_id=f"user-{uuid.uuid4().hex}", political_party="democrat")

        response = self.invoke_handler(event)

        # Matches `_seed_precomputed_csv`: first new democrat user lands on `control` (tie-break),
        # counter 1 -> assignment id `democrat-control-0001` -> CSV row index 1.
        expected_response = {
            "assigned_post_ids": [
                "democrat-control-post-1-a",
                "democrat-control-post-1-b",
            ],
            "already_assigned": True,
            "condition": "control",
        }
        _assert_equal(
            response,
            expected_response,
            "handler response should match seeded democrat/control row for assignment index 1",
        )

        assignments = self._query_user_assignments_for_iteration()
        _assert_equal(len(assignments), 1, "Exactly one user assignment row should exist")

    def test_existing_user_idempotency(self) -> None:
        """**Returning participant** path: existing user assignment must not be
        recreated or reassigned.
        """
        self._seed_party_condition_fixtures("democrat")
        event = self._make_event(prolific_id=f"user-{uuid.uuid4().hex}", political_party="democrat")

        expected_response = {
            "assigned_post_ids": [
                "democrat-control-post-1-a",
                "democrat-control-post-1-b",
            ],
            "already_assigned": True,
            "condition": "control",
        }
        expected_counters = {"democrat:control": 1}

        first_response = self.invoke_handler(event)
        counters_after_first = {
            row["study_unique_assignment_key"]: int(row["counter"])
            for row in self._query_counters_for_iteration()
        }

        second_response = self.invoke_handler(event)
        counters_after_second = {
            row["study_unique_assignment_key"]: int(row["counter"])
            for row in self._query_counters_for_iteration()
        }

        _assert_equal(
            first_response,
            expected_response,
            "first handler response should match seeded democrat/control row for assignment index 1",  # noqa
        )
        _assert_equal(
            second_response,
            expected_response,
            "second handler response should match first (idempotent)",
        )
        _assert_equal(
            counters_after_first,
            expected_counters,
            "counters after first call should reflect a single democrat control assignment",
        )
        _assert_equal(
            counters_after_second,
            expected_counters,
            "counters after second call should be unchanged",
        )
        assignments = self._query_user_assignments_for_iteration()
        _assert_equal(
            len(assignments), 1, "Repeat request should not create another assignment row"
        )

    def test_balance_across_conditions_same_party(self) -> None:
        """**Least-populated cell** selection for the same party across three new users.

        With empty counters, deterministic tie-break picks `control`, then `training`,
        then `training_assisted` (lexicographic order on `party:condition` keys at equal count).
        """
        self._seed_party_condition_fixtures("democrat")
        first_event = self._make_event(
            prolific_id=f"user-{uuid.uuid4().hex}", political_party="democrat"
        )
        second_event = self._make_event(
            prolific_id=f"user-{uuid.uuid4().hex}", political_party="democrat"
        )
        third_event = self._make_event(
            prolific_id=f"user-{uuid.uuid4().hex}", political_party="democrat"
        )

        expected_first_response = {
            "assigned_post_ids": [
                "democrat-control-post-1-a",
                "democrat-control-post-1-b",
            ],
            "already_assigned": True,
            "condition": "control",
        }
        expected_second_response = {
            "assigned_post_ids": [
                "democrat-training-post-1-a",
                "democrat-training-post-1-b",
            ],
            "already_assigned": True,
            "condition": "training",
        }
        expected_third_response = {
            "assigned_post_ids": [
                "democrat-training_assisted-post-1-a",
                "democrat-training_assisted-post-1-b",
            ],
            "already_assigned": True,
            "condition": "training_assisted",
        }
        expected_counters = {
            "democrat:control": 1,
            "democrat:training": 1,
            "democrat:training_assisted": 1,
        }

        first_response = self.invoke_handler(first_event)
        second_response = self.invoke_handler(second_event)
        third_response = self.invoke_handler(third_event)

        _assert_equal(
            first_response,
            expected_first_response,
            "first user should get democrat control row for assignment index 1",
        )
        _assert_equal(
            second_response,
            expected_second_response,
            "second user should get democrat training row for assignment index 1",
        )
        _assert_equal(
            third_response,
            expected_third_response,
            "third user should get democrat training_assisted row for assignment index 1",
        )

        counters = {
            row["study_unique_assignment_key"]: int(row["counter"])
            for row in self._query_counters_for_iteration()
        }
        _assert_equal(
            counters,
            expected_counters,
            "counters should show one assignment per democrat condition cell",
        )

    def test_party_isolation(self) -> None:
        """**Party isolation**: democrat and republican assignments stay in separate namespaces.

        The first time we run the handler (new democrat user), we expect `control` and the post IDs
        from the seeded democrat/control CSV row for assignment index 1.

        The second time we run the handler (new republican user, same study and iteration),
        we expect `control` and the post IDs from the seeded republican/control CSV row
        for assignment index 1, independent of the democrat user's assignment.
        """
        self._seed_party_condition_fixtures("democrat")
        self._seed_party_condition_fixtures("republican")

        democrat_event = self._make_event(
            prolific_id=f"user-{uuid.uuid4().hex}",
            political_party="democrat",
        )
        republican_event = self._make_event(
            prolific_id=f"user-{uuid.uuid4().hex}",
            political_party="republican",
        )

        expected_democrat_response = {
            "assigned_post_ids": [
                "democrat-control-post-1-a",
                "democrat-control-post-1-b",
            ],
            "already_assigned": True,
            "condition": "control",
        }
        expected_republican_response = {
            "assigned_post_ids": [
                "republican-control-post-1-a",
                "republican-control-post-1-b",
            ],
            "already_assigned": True,
            "condition": "control",
        }
        expected_counters = {"democrat:control": 1, "republican:control": 1}

        democrat_response = self.invoke_handler(democrat_event)
        republican_response = self.invoke_handler(republican_event)

        _assert_equal(
            democrat_response,
            expected_democrat_response,
            "democrat handler response should match seeded democrat/control row for assignment index 1",  # noqa
        )
        _assert_equal(
            republican_response,
            expected_republican_response,
            "republican handler response should match seeded republican/control row for assignment index 1",  # noqa
        )

        assignments = self._query_user_assignments_for_iteration()
        _assert_equal(len(assignments), 2, "Expected exactly two user assignment rows")

        counters = {
            row["study_unique_assignment_key"]: int(row["counter"])
            for row in self._query_counters_for_iteration()
        }
        _assert_equal(
            counters,
            expected_counters,
            "each party should have incremented only its own control cell once",
        )

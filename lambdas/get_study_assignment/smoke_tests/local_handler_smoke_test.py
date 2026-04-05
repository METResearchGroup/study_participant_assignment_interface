"""Local smoke tests for get_study_assignment handler orchestration.

Run:
    PYTHONPATH=. AWS_REGION=us-east-2 USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
    STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
    uv run python lambdas/get_study_assignment/smoke_tests/local_handler_smoke_test.py
"""

from __future__ import annotations

import json
import os
import traceback
import uuid
from collections.abc import Iterable
from typing import Any

import boto3
import pandas as pd
from boto3.dynamodb.conditions import Key

import lambdas.get_study_assignment.handler as h
from jobs.mirrorview.constants import DEFAULT_BUCKET, DEFAULT_S3_PREFIX, OUTPUT_RECORDS_FILENAME
from jobs.mirrorview.generate_assignment_ids import generate_single_assignment_id
from lib.s3 import S3
from lib.timestamp_utils import get_current_timestamp

TEST_ENV_PREFIX = "smoke"


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}. Expected {expected!r}, got {actual!r}")


class HandlerSmokeTestBase:
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

        # Ensure handler uses this test's table names and region.
        h.region_name = self.region_name
        h.user_assignments_table_name = self.user_assignments_table_name
        h.study_assignment_counter_table_name = self.assignment_counter_table_name
        h.s3 = self.s3_store

    def teardown(self) -> None:
        if not hasattr(self, "assignment_counter_table"):
            return
        self._cleanup_counter_rows_for_iteration()
        self._cleanup_user_assignments_for_iteration()
        self._cleanup_s3_fixture_objects()

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
            query_kwargs = {"KeyConditionExpression": key_condition}
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


class TestHandlerSmoke(HandlerSmokeTestBase):
    def test_new_user_happy_path(self) -> None:
        self._seed_party_condition_fixtures("democrat")
        event = self._make_event(prolific_id=f"user-{uuid.uuid4().hex}", political_party="democrat")

        response = h.handler(event, None)

        _assert_true(
            isinstance(response["assigned_post_ids"], list), "assigned_post_ids must be list"
        )
        _assert_true(len(response["assigned_post_ids"]) > 0, "assigned_post_ids must be non-empty")
        _assert_equal(response["already_assigned"], True, "already_assigned must be True")
        _assert_true(
            response["condition"] in {"control", "training_assisted"},
            "condition must be one of default conditions",
        )

        assignments = self._query_user_assignments_for_iteration()
        _assert_equal(len(assignments), 1, "Exactly one user assignment row should exist")

    def test_existing_user_idempotency(self) -> None:
        self._seed_party_condition_fixtures("democrat")
        event = self._make_event(prolific_id=f"user-{uuid.uuid4().hex}", political_party="democrat")

        first_response = h.handler(event, None)
        counters_after_first = {
            row["study_unique_assignment_key"]: int(row["counter"])
            for row in self._query_counters_for_iteration()
        }

        second_response = h.handler(event, None)
        counters_after_second = {
            row["study_unique_assignment_key"]: int(row["counter"])
            for row in self._query_counters_for_iteration()
        }

        _assert_equal(
            second_response, first_response, "Second response should equal first response"
        )
        _assert_equal(
            counters_after_second, counters_after_first, "Counters changed on repeat request"
        )
        assignments = self._query_user_assignments_for_iteration()
        _assert_equal(
            len(assignments), 1, "Repeat request should not create another assignment row"
        )

    def test_balance_across_conditions_same_party(self) -> None:
        self._seed_party_condition_fixtures("democrat")
        first_event = self._make_event(
            prolific_id=f"user-{uuid.uuid4().hex}", political_party="democrat"
        )
        second_event = self._make_event(
            prolific_id=f"user-{uuid.uuid4().hex}", political_party="democrat"
        )

        first_response = h.handler(first_event, None)
        second_response = h.handler(second_event, None)

        _assert_equal(
            first_response["condition"],
            "control",
            "Tie-break should deterministically choose control first",
        )
        _assert_equal(
            {first_response["condition"], second_response["condition"]},
            {"control", "training_assisted"},
            "Two users should distribute across both conditions",
        )

        counters = {
            row["study_unique_assignment_key"]: int(row["counter"])
            for row in self._query_counters_for_iteration()
        }
        _assert_equal(
            counters.get("democrat:control"), 1, "Expected one democrat control assignment"
        )
        _assert_equal(
            counters.get("democrat:training_assisted"),
            1,
            "Expected one democrat training_assisted assignment",
        )

    def test_party_isolation(self) -> None:
        democrat_fixtures = self._seed_party_condition_fixtures("democrat")
        republican_fixtures = self._seed_party_condition_fixtures("republican")

        democrat_event = self._make_event(
            prolific_id=f"user-{uuid.uuid4().hex}",
            political_party="democrat",
        )
        republican_event = self._make_event(
            prolific_id=f"user-{uuid.uuid4().hex}",
            political_party="republican",
        )

        democrat_response = h.handler(democrat_event, None)
        republican_response = h.handler(republican_event, None)

        _assert_equal(
            democrat_response["condition"], "control", "First democrat assignment should be control"
        )
        _assert_equal(
            republican_response["condition"],
            "control",
            "First republican assignment should be control",
        )

        assignments = self._query_user_assignments_for_iteration()
        _assert_equal(len(assignments), 2, "Expected exactly two user assignment rows")

        assignment_payloads = [json.loads(item["payload"]) for item in assignments]
        by_party = {}
        for payload in assignment_payloads:
            metadata = json.loads(payload["metadata"])
            by_party[metadata["political_party"]] = payload

        _assert_true("democrat" in by_party, "Democrat payload missing")
        _assert_true("republican" in by_party, "Republican payload missing")

        _assert_equal(
            by_party["democrat"]["s3_key"],
            democrat_fixtures["control"],
            "Democrat should use democrat fixture key",
        )
        _assert_equal(
            by_party["republican"]["s3_key"],
            republican_fixtures["control"],
            "Republican should use republican fixture key",
        )
        _assert_true(
            by_party["democrat"]["assignment_id"].startswith("democrat-control-"),
            "Democrat assignment id should stay in democrat namespace",
        )
        _assert_true(
            by_party["republican"]["assignment_id"].startswith("republican-control-"),
            "Republican assignment id should stay in republican namespace",
        )

        counters = {
            row["study_unique_assignment_key"]: int(row["counter"])
            for row in self._query_counters_for_iteration()
        }
        _assert_equal(counters.get("democrat:control"), 1, "Democrat counter should be isolated")
        _assert_equal(
            counters.get("republican:control"), 1, "Republican counter should be isolated"
        )


TEST_CLASSES = [TestHandlerSmoke]


def _iter_test_methods(test_instance) -> list[str]:
    methods = [
        name
        for name in dir(test_instance)
        if name.startswith("test_") and callable(getattr(test_instance, name))
    ]
    return sorted(methods)


def run_smoke_tests() -> int:
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
    raise SystemExit(run_smoke_tests())


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TEST_ENV_PREFIX = "dev"


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _unique_suffix() -> str:
    return uuid.uuid4().hex


def _assert_equal(actual, expected, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}. Expected {expected}, got {actual}")


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.append(str(root))

    from lib.dynamodb import (  # pylint: disable=import-error
        UserAssignmentPayload,
        get_user_assignment,
        increment_assignment_counter,
        put_user_assignment,
    )

    region_name = _require_env("AWS_REGION")
    user_assignments_table = _require_env("USER_ASSIGNMENTS_TABLE_NAME")
    assignment_counter_table = _require_env("STUDY_ASSIGNMENT_COUNTER_TABLE_NAME")

    study_id = f"study-{_unique_suffix()}"
    study_iteration_id = f"{TEST_ENV_PREFIX}_iteration-{_unique_suffix()}"
    user_id = f"user-{_unique_suffix()}"

    payload_data = {
        "s3_bucket": "test-bucket",
        "s3_key": f"assignments/{_unique_suffix()}.json",
        "assignment_id": f"assignment-{_unique_suffix()}",
        "metadata": json.dumps(
            {
                "variant": "control",
                "note": "smoke-test",
            }
        ),
    }
    payload_model = UserAssignmentPayload.model_validate(payload_data)

    # user_assignments read/write
    stored = put_user_assignment(
        study_id=study_id,
        study_iteration_id=study_iteration_id,
        user_id=user_id,
        payload=payload_model,
        table_name=user_assignments_table,
        region_name=region_name,
    )
    fetched = get_user_assignment(
        study_id=study_id,
        study_iteration_id=study_iteration_id,
        user_id=user_id,
        table_name=user_assignments_table,
        region_name=region_name,
    )
    if fetched is None:
        raise AssertionError("get_user_assignment returned None after put_user_assignment")

    _assert_equal(fetched.study_id, stored.study_id, "Study ID mismatch")
    _assert_equal(fetched.user_id, stored.user_id, "User ID mismatch")
    _assert_equal(
        fetched.payload.model_dump(),
        stored.payload.model_dump(),
        "Payload mismatch",
    )

    # study_assignment_counter on-miss increment
    study_unique_assignment_key = f"assignment-key-{_unique_suffix()}"
    first_counter = increment_assignment_counter(
        study_id=study_id,
        study_iteration_id=study_iteration_id,
        study_unique_assignment_key=study_unique_assignment_key,
        table_name=assignment_counter_table,
        region_name=region_name,
    )
    _assert_equal(first_counter, 1, "First counter increment should return 1")

    # concurrent increments for a fresh key
    concurrent_key = f"assignment-key-{_unique_suffix()}"
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(
                increment_assignment_counter,
                study_id=study_id,
                study_iteration_id=study_iteration_id,
                study_unique_assignment_key=concurrent_key,
                table_name=assignment_counter_table,
                region_name=region_name,
            )
            for _ in range(5)
        ]
        results = [future.result() for future in futures]

    sorted_results = sorted(results)
    _assert_equal(
        sorted_results,
        list(range(1, 6)),
        "Concurrent counter values should be sequential and distinct",
    )

    print("DynamoDB smoke test passed: read/write and concurrent increment checks succeeded.")


if __name__ == "__main__":
    main()

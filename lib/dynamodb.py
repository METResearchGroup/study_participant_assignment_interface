from __future__ import annotations

import json
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from pydantic import BaseModel

from lib.timestamp_utils import get_current_timestamp


class UserAssignmentPayload(BaseModel):
    s3_bucket: str
    s3_key: str
    assignment_id: str
    metadata: str


class UserAssignmentRecord(BaseModel):
    study_id: str
    study_iteration_id: str
    user_id: str
    iteration_user_key: str
    payload: UserAssignmentPayload
    created_at: str


class StudyAssignmentCounterRecord(BaseModel):
    study_id: str
    study_iteration_id: str
    study_unique_assignment_key: str
    iteration_assignment_key: str
    counter: int
    created_at: str
    last_updated_at: str


class AssignmentCounterConflictError(RuntimeError):
    """Raised when a compare-and-increment counter update loses a race."""


_COMPOSITE_KEY_SEP = "#"


def _assert_component_has_no_composite_sep(name: str, value: str) -> None:
    if _COMPOSITE_KEY_SEP in value:
        raise ValueError(
            f"{name} must not contain {_COMPOSITE_KEY_SEP!r} "
            f"(ambiguous composite key); got {value!r}"
        )


def _build_iteration_user_key(study_iteration_id: str, user_id: str) -> str:
    _assert_component_has_no_composite_sep("study_iteration_id", study_iteration_id)
    _assert_component_has_no_composite_sep("user_id", user_id)
    return f"{study_iteration_id}{_COMPOSITE_KEY_SEP}{user_id}"


def _build_iteration_assignment_key(
    study_iteration_id: str, study_unique_assignment_key: str
) -> str:
    _assert_component_has_no_composite_sep("study_iteration_id", study_iteration_id)
    _assert_component_has_no_composite_sep(
        "study_unique_assignment_key", study_unique_assignment_key
    )
    return f"{study_iteration_id}{_COMPOSITE_KEY_SEP}{study_unique_assignment_key}"


def _get_table(table_name: str, region_name: str | None = None):
    resource_kwargs: dict[str, Any] = {}
    if region_name:
        resource_kwargs["region_name"] = region_name
    dynamodb: Any = boto3.resource("dynamodb", **resource_kwargs)
    return dynamodb.Table(table_name)


def _serialize_payload(payload: UserAssignmentPayload) -> str:
    return json.dumps(payload.model_dump())


def _deserialize_payload(raw_payload: str) -> UserAssignmentPayload:
    data = json.loads(raw_payload)
    return UserAssignmentPayload.model_validate(data)


def get_user_assignment(
    *,
    study_id: str,
    study_iteration_id: str,
    user_id: str,
    table_name: str,
    region_name: str | None = None,
) -> UserAssignmentRecord | None:
    table = _get_table(table_name, region_name=region_name)
    iteration_user_key = _build_iteration_user_key(study_iteration_id, user_id)
    response = table.get_item(
        Key={
            "study_id": study_id,
            "iteration_user_key": iteration_user_key,
        },
        ConsistentRead=True,
    )
    item = response.get("Item")
    if not item:
        return None

    payload = _deserialize_payload(item["payload"])
    return UserAssignmentRecord(
        study_id=item["study_id"],
        study_iteration_id=item["study_iteration_id"],
        user_id=item["user_id"],
        iteration_user_key=item["iteration_user_key"],
        payload=payload,
        created_at=item["created_at"],
    )


def put_user_assignment(
    *,
    study_id: str,
    study_iteration_id: str,
    user_id: str,
    payload: UserAssignmentPayload,
    table_name: str,
    region_name: str | None = None,
) -> UserAssignmentRecord:
    table = _get_table(table_name, region_name=region_name)
    iteration_user_key = _build_iteration_user_key(study_iteration_id, user_id)
    created_at = get_current_timestamp()

    item = {
        "study_id": study_id,
        "iteration_user_key": iteration_user_key,
        "study_iteration_id": study_iteration_id,
        "user_id": user_id,
        "payload": _serialize_payload(payload),
        "created_at": created_at,
    }
    table.put_item(
        Item=item,
        ConditionExpression=(
            "attribute_not_exists(study_id) AND attribute_not_exists(iteration_user_key)"
        ),
    )

    return UserAssignmentRecord(
        study_id=study_id,
        study_iteration_id=study_iteration_id,
        user_id=user_id,
        iteration_user_key=iteration_user_key,
        payload=payload,
        created_at=created_at,
    )


def increment_assignment_counter(
    *,
    study_id: str,
    study_iteration_id: str,
    study_unique_assignment_key: str,
    table_name: str,
    region_name: str | None = None,
) -> int:
    table = _get_table(table_name, region_name=region_name)
    iteration_assignment_key = _build_iteration_assignment_key(
        study_iteration_id, study_unique_assignment_key
    )
    timestamp = get_current_timestamp()

    response = table.update_item(
        Key={
            "study_id": study_id,
            "iteration_assignment_key": iteration_assignment_key,
        },
        UpdateExpression=(
            "SET #counter = if_not_exists(#counter, :zero) + :one, "
            "#updated_at = :timestamp, "
            "#created_at = if_not_exists(#created_at, :timestamp), "
            "#study_iteration_id = if_not_exists(#study_iteration_id, :study_iteration_id), "
            "#study_unique_assignment_key = if_not_exists("
            "#study_unique_assignment_key, :study_unique_assignment_key)"
        ),
        ExpressionAttributeNames={
            "#counter": "counter",
            "#created_at": "created_at",
            "#updated_at": "last_updated_at",
            "#study_iteration_id": "study_iteration_id",
            "#study_unique_assignment_key": "study_unique_assignment_key",
        },
        ExpressionAttributeValues={
            ":zero": 0,
            ":one": 1,
            ":timestamp": timestamp,
            ":study_iteration_id": study_iteration_id,
            ":study_unique_assignment_key": study_unique_assignment_key,
        },
        ReturnValues="UPDATED_NEW",
    )

    attributes = response.get("Attributes", {})
    counter = attributes.get("counter")
    if counter is None:
        raise RuntimeError("DynamoDB update did not return a counter value.")
    return int(counter)


def list_assignment_counters_for_party(
    *,
    study_id: str,
    study_iteration_id: str,
    political_party: str,
    table_name: str,
    region_name: str | None = None,
) -> list[StudyAssignmentCounterRecord]:
    """List counter rows for one (study, iteration, political_party)."""
    table = _get_table(table_name, region_name=region_name)
    iteration_party_prefix = _build_iteration_assignment_key(
        study_iteration_id, f"{political_party}:"
    )
    response = table.query(
        KeyConditionExpression=Key("study_id").eq(study_id)
        & Key("iteration_assignment_key").begins_with(iteration_party_prefix),
        ConsistentRead=True,
    )
    items = response.get("Items", [])
    records: list[StudyAssignmentCounterRecord] = []
    for item in items:
        iteration_assignment_key = item["iteration_assignment_key"]
        unique_assignment_key = item.get(
            "study_unique_assignment_key",
            iteration_assignment_key.split(_COMPOSITE_KEY_SEP, 1)[1],
        )
        records.append(
            StudyAssignmentCounterRecord(
                study_id=item["study_id"],
                study_iteration_id=item.get("study_iteration_id", study_iteration_id),
                study_unique_assignment_key=unique_assignment_key,
                iteration_assignment_key=iteration_assignment_key,
                counter=int(item.get("counter", 0)),
                created_at=item.get("created_at", ""),
                last_updated_at=item.get("last_updated_at", ""),
            )
        )
    return records


def compare_and_increment_assignment_counter(
    *,
    study_id: str,
    study_iteration_id: str,
    study_unique_assignment_key: str,
    expected_counter: int,
    table_name: str,
    region_name: str | None = None,
) -> int:
    """Compare-and-increment a counter row. Raises on compare mismatch."""
    table = _get_table(table_name, region_name=region_name)
    iteration_assignment_key = _build_iteration_assignment_key(
        study_iteration_id, study_unique_assignment_key
    )
    timestamp = get_current_timestamp()
    try:
        response = table.update_item(
            Key={
                "study_id": study_id,
                "iteration_assignment_key": iteration_assignment_key,
            },
            ConditionExpression=(
                "(attribute_not_exists(#counter) AND :expected_counter = :zero) "
                "OR #counter = :expected_counter"
            ),
            UpdateExpression=(
                "SET #counter = if_not_exists(#counter, :zero) + :one, "
                "#updated_at = :timestamp, "
                "#created_at = if_not_exists(#created_at, :timestamp), "
                "#study_iteration_id = if_not_exists(#study_iteration_id, :study_iteration_id), "
                "#study_unique_assignment_key = if_not_exists("
                "#study_unique_assignment_key, :study_unique_assignment_key)"
            ),
            ExpressionAttributeNames={
                "#counter": "counter",
                "#created_at": "created_at",
                "#updated_at": "last_updated_at",
                "#study_iteration_id": "study_iteration_id",
                "#study_unique_assignment_key": "study_unique_assignment_key",
            },
            ExpressionAttributeValues={
                ":expected_counter": expected_counter,
                ":zero": 0,
                ":one": 1,
                ":timestamp": timestamp,
                ":study_iteration_id": study_iteration_id,
                ":study_unique_assignment_key": study_unique_assignment_key,
            },
            ReturnValues="UPDATED_NEW",
        )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "ConditionalCheckFailedException":
            raise AssignmentCounterConflictError(
                "Counter changed before compare-and-increment completed."
            ) from exc
        raise

    attributes = response.get("Attributes", {})
    counter = attributes.get("counter")
    if counter is None:
        raise RuntimeError("DynamoDB compare-and-increment did not return a counter value.")
    return int(counter)

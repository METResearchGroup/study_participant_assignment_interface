from __future__ import annotations

import json
from typing import Any

import boto3
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


def _build_iteration_user_key(study_iteration_id: str, user_id: str) -> str:
    return f"{study_iteration_id}#{user_id}"


def _build_iteration_assignment_key(
    study_iteration_id: str, study_unique_assignment_key: str
) -> str:
    return f"{study_iteration_id}#{study_unique_assignment_key}"


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
        }
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
    table.put_item(Item=item)

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

import json

import pandas as pd

from lib.dynamodb import (
    UserAssignmentPayload,
    UserAssignmentRecord,
    get_user_assignment,
    put_user_assignment,
)
from lib.s3 import S3

from jobs.mirrorview.constants import (
    DEFAULT_BUCKET,
    DEFAULT_S3_PREFIX,
    OUTPUT_RECORDS_FILENAME,
)
from jobs.mirrorview.generate_assignment_ids import generate_single_assignment_id

user_assignments_table_name = "user_assignments"
region_name = "us-east-2"

s3 = S3(bucket=DEFAULT_BUCKET)


def get_user_assignment_record_if_exists(
    *,
    study_id: str,
    study_iteration_id: str,
    prolific_id: str,
):
    user_assignment_record: UserAssignmentRecord | None = get_user_assignment(
        study_id=study_id,
        study_iteration_id=study_iteration_id,
        user_id=prolific_id,
        table_name=user_assignments_table_name,
        region_name=region_name,
    )
    return user_assignment_record


# basically, we (1) iterate the DynamoDB counter, and then (2) we
# determine the assignment ID.
def assign_user_to_condition(prolific_id: str, political_party: str) -> dict:
    condition = ""
    total_in_condition = 0  # includes this new user

    return {"condition": condition, "total_in_condition": total_in_condition}


def get_latest_uploaded_precomputed_assignments_s3_key(
    political_party: str,
    condition: str,
) -> str:
    """Return the latest uploaded precomputed assignments S3 key for a given political party and condition."""
    precomputed_keys: list[str] = s3.list_keys_ordered(prefix=DEFAULT_S3_PREFIX)
    relevant_precomputed_keys: list[str] = [
        key
        for key in precomputed_keys
        if political_party in key and condition in key and key.endswith(OUTPUT_RECORDS_FILENAME)
    ]
    return sorted(relevant_precomputed_keys, reverse=True)[0]


# TODO: gotta think through how to set this logic...
# TODO: also, for test e2e runs, don't forget to prepend the study_iteration_id
# with "test_" or "dev_"
def set_user_assignment_record(
    *,
    study_id: str,
    study_iteration_id: str,
    prolific_id: str,
    political_party: str,
):
    """Set the user assignment record for a given user.

    Algorithm:
    1.
    """
    assigned_condition_dict: dict = assign_user_to_condition(
        prolific_id=prolific_id, political_party=political_party
    )
    assigned_condition = assigned_condition_dict["condition"]
    total_in_condition = assigned_condition_dict["total_in_condition"]

    assignment_id: str = generate_single_assignment_id(
        political_party=political_party,
        condition=assigned_condition,
        index=total_in_condition,
    )
    metadata: dict[str, str] = {
        "political_party": political_party,
        "condition": assigned_condition,
    }
    s3_key: str = get_latest_uploaded_precomputed_assignments_s3_key(
        political_party=political_party,
        condition=assigned_condition,
    )
    raw_payload_dict = {
        "s3_bucket": DEFAULT_BUCKET,
        "s3_key": s3_key,
        "assignment_id": assignment_id,
        "metadata": metadata,
    }
    payload = UserAssignmentPayload(**raw_payload_dict)

    user_assignment_record: UserAssignmentRecord = put_user_assignment(
        study_id=study_id,
        study_iteration_id=study_iteration_id,
        user_id=prolific_id,
        payload=payload,
        table_name=user_assignments_table_name,
        region_name=region_name,
    )
    return user_assignment_record


def get_or_set_user_assignment_record(
    *,
    study_id: str,
    study_iteration_id: str,
    prolific_id: str,
    political_party: str,
) -> UserAssignmentRecord:
    user_assignment_record: UserAssignmentRecord | None = get_user_assignment_record_if_exists(
        study_id=study_id, study_iteration_id=study_iteration_id, prolific_id=prolific_id
    )
    if not user_assignment_record:
        user_assignment_record = set_user_assignment_record(
            study_id=study_id,
            study_iteration_id=study_iteration_id,
            prolific_id=prolific_id,
            political_party=political_party,
        )
    return user_assignment_record


def load_latest_precomputed_assignments(s3_key: str) -> pd.DataFrame:
    return pd.DataFrame()  # TODO: implement


def get_precomputed_assignment(
    user_assignment_record: UserAssignmentRecord, user_assignment_payload: UserAssignmentPayload
):
    latest_precomputed_assignments: pd.DataFrame = load_latest_precomputed_assignments(
        s3_key=user_assignment_payload.s3_key
    )
    assignment = latest_precomputed_assignments[
        latest_precomputed_assignments["id"] == user_assignment_payload.assignment_id
    ]
    if assignment.empty:
        raise ValueError(f"Assignment not found for user {user_assignment_record.user_id}")
    assigned_post_ids: list[str] = assignment["assigned_post_ids"].tolist()
    return assigned_post_ids


def main(study_id: str, study_iteration_id: str, prolific_id: str, political_party: str):

    # get the record for a given user if it exists. Otherwise, set it.
    user_assignment_record: UserAssignmentRecord = get_or_set_user_assignment_record(
        study_id=study_id,
        study_iteration_id=study_iteration_id,
        prolific_id=prolific_id,
        political_party=political_party,
    )

    user_assignment_payload: UserAssignmentPayload = user_assignment_record.payload
    user_assignment_metadata: dict = json.loads(user_assignment_payload.metadata)
    condition = user_assignment_metadata["condition"]

    # given the record for the given user and what condition we've assigned for
    # them, get the actual posts they've been assigned (which we precomputed)
    assigned_post_ids: list[str] = get_precomputed_assignment(
        user_assignment_record=user_assignment_record,
        user_assignment_payload=user_assignment_payload,
    )

    # return payload. Matches interface expectations from UI.
    return {
        "assigned_post_ids": assigned_post_ids,
        "already_assigned": True,
        "condition": condition,
    }


def handler(event, context):
    return main(
        study_id=event["study_id"],
        study_iteration_id=event["study_iteration_id"],
        prolific_id=event["prolific_id"],
        political_party=event["political_party"],
    )

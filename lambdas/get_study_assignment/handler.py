import json

import pandas as pd

from lib.dynamodb import (
    UserAssignmentPayload,
    UserAssignmentRecord,
    get_user_assignment,
    put_user_assignment,
)

user_assignments_table_name = "user_assignments"
region_name = "us-east-2"

DEFAULT_BUCKET = "jspsych-mirror-view-3"


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


def assign_user_to_condition(prolific_id: str, political_party: str) -> str:
    return ""  # TODO: calculate


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
    assigned_condition: str = assign_user_to_condition(
        prolific_id=prolific_id, political_party=political_party
    )
    print(assigned_condition)
    # ... think through this logic ...
    assignment_id = ""  # TODO: calculate
    metadata = {
        "political_party": political_party,
        "condition": assigned_condition,
    }  # TODO: calculate
    s3_key = ""  # TODO: calculate
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


def load_latest_precomputed_assignments(
    political_party: str,
    condition: str,
) -> pd.DataFrame:
    return pd.DataFrame() # TODO: implement

def get_precomputed_assignment(
    user_assignment_record: UserAssignmentRecord,
    user_assignment_payload: UserAssignmentPayload,
    political_party: str,
    condition: str,
):
    latest_precomputed_assignments: pd.DataFrame = load_latest_precomputed_assignments(
        political_party=political_party,
        condition=condition,
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
    political_party = user_assignment_metadata["political_party"]
    condition = user_assignment_metadata["condition"]

    # given the record for the given user and what condition we've assigned for
    # them, get the actual posts they've been assigned (which we precomputed)
    assigned_post_ids: list[str] = get_precomputed_assignment(
        user_assignment_record=user_assignment_record,
        user_assignment_payload=user_assignment_payload,
        political_party=political_party,
        condition=condition,
    )

    # return payload. Matches interface expectations from UI.
    return {
        "assigned_post_ids": assigned_post_ids,
        "already_assigned": True, # TODO: implement
        "condition": condition
    }


def handler(event, context):
    return main(
        study_id=event["study_id"],
        study_iteration_id=event["study_iteration_id"],
        prolific_id=event["prolific_id"],
        political_party=event["political_party"],
    )

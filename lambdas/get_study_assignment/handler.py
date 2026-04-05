import json

import pandas as pd

from jobs.mirrorview.constants import (
    DEFAULT_BUCKET,
    DEFAULT_S3_PREFIX,
    OUTPUT_RECORDS_FILENAME,
)
from jobs.mirrorview.generate_assignment_ids import generate_single_assignment_id
from lib.dynamodb import (
    AssignmentCounterConflictError,
    StudyAssignmentCounterRecord,
    UserAssignmentPayload,
    UserAssignmentRecord,
    compare_and_increment_assignment_counter,
    get_user_assignment,
    list_assignment_counters_for_party,
    put_user_assignment,
)
from lib.s3 import S3

user_assignments_table_name = "user_assignments"
study_assignment_counter_table_name = "study_assignment_counter"
region_name = "us-east-2"
MAX_ASSIGNMENT_RETRIES = 5
DEFAULT_STUDY_CONDITIONS = ("control", "training_assisted")

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


def select_least_assignment_party_condition_key(
    *,
    study_id: str,
    study_iteration_id: str,
    political_party: str,
) -> tuple[str, int]:
    """Select the least assignment party condition key for a given study,
    iteration, and party. Reads from DynamoDB and returns both the key
    and the expected counter value for the key.

    We return the expected counter value for the key because we need to
    increment the counter after we've selected the key and we have to verify
    that the counter hasn't changed since we read it.
    """
    party_counter_records: list[StudyAssignmentCounterRecord] = list_assignment_counters_for_party(
        study_id=study_id,
        study_iteration_id=study_iteration_id,
        political_party=political_party,
        table_name=study_assignment_counter_table_name,
        region_name=region_name,
    )
    # output is, e.g,. {"democrat:control": 5, "democrat:training_assisted": 3},
    # giving the counts for each party x condition combination, for the given
    # study_id and study_iteration_id.
    key_to_counter: dict[str, int] = {
        record.study_unique_assignment_key: int(record.counter) for record in party_counter_records
    }
    # filtering for the party that we care about.
    # e.g., input = {"democrat:control": 5, "democrat:training_assisted": 3, "republican:control": 2, "republican:training_assisted": 4}, # noqa
    # output (if party=democrat) = {"democrat:control": 5, "democrat:training_assisted": 3}
    key_to_counter = {
        key: counter
        for key, counter in key_to_counter.items()
        if key.startswith(f"{political_party}:") and ":" in key
    }

    # get all possibly party x condition keys available
    all_candidate_keys: list[str] = sorted(
        set(key_to_counter.keys())
        | {f"{political_party}:{condition}" for condition in DEFAULT_STUDY_CONDITIONS}
    )
    if not all_candidate_keys:
        raise ValueError(f"No candidate assignment keys for political_party={political_party!r}")

    # Choose the currently smallest cell; tie-break by key for determinism.
    selected_unique_key = min(
        all_candidate_keys,
        key=lambda key: (key_to_counter.get(key, 0), key),
    )
    expected_counter = key_to_counter.get(selected_unique_key, 0)
    return selected_unique_key, expected_counter


def assign_user_to_condition(
    *,
    study_id: str,
    study_iteration_id: str,
    political_party: str,
) -> dict:
    """We assign a user to a condition based on which condition has the least
    number of users assigned to it, for the given political party.

    We need to, at some level, (1) read the counts and (2) update accordingly.
    This current approach is the easiest for that. We read the counts and
    then attempt to increment the counter, assuming that it hasn't changed
    counts (i.e., another lambda hasn't already incremented it for a different
    user). If this fails, we retry, up to MAX_ASSIGNMENT_RETRIES times.

    This concurrency pattern is straightforward to implement and for our
    (very small) use case, it should be sufficient. After all, for 1,000-2,000
    users, this TOCTOU race condition is very unlikely anyways, but we want it
    here in case it indeed does happen.
    """
    for _ in range(MAX_ASSIGNMENT_RETRIES):
        try:
            selected_assignment_key, expected_counter = select_least_assignment_party_condition_key(
                study_id=study_id,
                study_iteration_id=study_iteration_id,
                political_party=political_party,
            )
            total_in_condition = compare_and_increment_assignment_counter(
                study_id=study_id,
                study_iteration_id=study_iteration_id,
                study_unique_assignment_key=selected_assignment_key,
                expected_counter=expected_counter,
                table_name=study_assignment_counter_table_name,
                region_name=region_name,
            )
        except AssignmentCounterConflictError:
            continue

        condition = selected_assignment_key.split(":", 1)[1]
        return {"condition": condition, "total_in_condition": total_in_condition}

    raise RuntimeError(
        f"Failed to assign user after {MAX_ASSIGNMENT_RETRIES} retries for "
        f"study_id={study_id!r}, study_iteration_id={study_iteration_id!r}, "
        f"political_party={political_party!r}"
    )


def get_latest_uploaded_precomputed_assignments_s3_key(
    political_party: str,
    condition: str,
) -> str:
    """Return the latest uploaded precomputed assignments S3 key for a
    given political party and condition."""
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
        study_id=study_id,
        study_iteration_id=study_iteration_id,
        political_party=political_party,
    )
    assigned_condition = assigned_condition_dict["condition"]
    total_in_condition = assigned_condition_dict["total_in_condition"]
    if total_in_condition <= 0:
        raise ValueError(f"Invalid counter for assignment generation: {total_in_condition!r}")

    assignment_id: str = generate_single_assignment_id(
        political_party=political_party,
        condition=assigned_condition,
        # DynamoDB counters are 1-based after increment; assignment IDs are 0-based.
        index=total_in_condition - 1,
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
        "metadata": json.dumps(metadata),
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
    return s3.load_csv_to_dataframe(key=s3_key)


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
    assigned_post_ids_raw = assignment.iloc[0]["assigned_post_ids"]
    if isinstance(assigned_post_ids_raw, str):
        return json.loads(assigned_post_ids_raw)
    if isinstance(assigned_post_ids_raw, list):
        return assigned_post_ids_raw
    raise ValueError(
        f"Unexpected assigned_post_ids format: {type(assigned_post_ids_raw)!r} "
        f"for user {user_assignment_record.user_id!r}"
    )


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

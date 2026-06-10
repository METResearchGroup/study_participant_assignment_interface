import json

import pandas as pd
import yaml

from jobs.mirrorview.config_loader import (
    MirrorViewConfig,
    parse_assignment_batch_uri,
    validate_assignment_batch_uri,
)
from jobs.mirrorview.constants import OUTPUT_RECORDS_FILENAME
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
    study_conditions: tuple[str, ...],
) -> tuple[str, int]:
    """Select the least assignment party condition key for a given study,
    iteration, and party. Reads from DynamoDB and returns both the key
    and the expected counter value for the key.
    """
    party_counter_records: list[StudyAssignmentCounterRecord] = list_assignment_counters_for_party(
        study_id=study_id,
        study_iteration_id=study_iteration_id,
        political_party=political_party,
        table_name=study_assignment_counter_table_name,
        region_name=region_name,
    )
    key_to_counter: dict[str, int] = {
        record.study_unique_assignment_key: int(record.counter) for record in party_counter_records
    }
    key_to_counter = {
        key: counter
        for key, counter in key_to_counter.items()
        if key.startswith(f"{political_party}:") and ":" in key
    }

    all_candidate_keys: list[str] = sorted(
        set(key_to_counter.keys())
        | {f"{political_party}:{condition}" for condition in study_conditions}
    )
    if not all_candidate_keys:
        raise ValueError(f"No candidate assignment keys for political_party={political_party!r}")

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
    study_conditions: tuple[str, ...],
) -> dict:
    for _ in range(MAX_ASSIGNMENT_RETRIES):
        try:
            selected_assignment_key, expected_counter = select_least_assignment_party_condition_key(
                study_id=study_id,
                study_iteration_id=study_iteration_id,
                political_party=political_party,
                study_conditions=study_conditions,
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


def build_precomputed_assignments_s3_key(
    *,
    batch_key_prefix: str,
    political_party: str,
    condition: str,
) -> str:
    return f"{batch_key_prefix}/{political_party}/{condition}/{OUTPUT_RECORDS_FILENAME}"


def load_batch_config(*, s3: S3, batch_key_prefix: str) -> MirrorViewConfig:
    config_key = f"{batch_key_prefix}/config.yaml"
    config_text = s3.load_text(config_key)
    raw = yaml.safe_load(config_text)
    return MirrorViewConfig.model_validate(raw)


def set_user_assignment_record(
    *,
    study_id: str,
    study_iteration_id: str,
    prolific_id: str,
    political_party: str,
    mirrorview_config: MirrorViewConfig,
    batch_key_prefix: str,
):
    """Set the user assignment record for a given user."""
    study_conditions = mirrorview_config.configured_conditions()
    assigned_condition_dict: dict = assign_user_to_condition(
        study_id=study_id,
        study_iteration_id=study_iteration_id,
        political_party=political_party,
        study_conditions=study_conditions,
    )
    assigned_condition = assigned_condition_dict["condition"]
    total_in_condition = assigned_condition_dict["total_in_condition"]
    if total_in_condition <= 0:
        raise ValueError(f"Invalid counter for assignment generation: {total_in_condition!r}")

    assignment_id: str = generate_single_assignment_id(
        political_party=political_party,
        condition=assigned_condition,
        index=total_in_condition,
    )
    metadata: dict[str, str] = {
        "political_party": political_party,
        "condition": assigned_condition,
    }
    s3_key: str = build_precomputed_assignments_s3_key(
        batch_key_prefix=batch_key_prefix,
        political_party=political_party,
        condition=assigned_condition,
    )
    raw_payload_dict = {
        "s3_bucket": mirrorview_config.s3.bucket,
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
    mirrorview_config: MirrorViewConfig,
    batch_key_prefix: str,
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
            mirrorview_config=mirrorview_config,
            batch_key_prefix=batch_key_prefix,
        )
    return user_assignment_record


def load_precomputed_assignments(*, bucket: str, s3_key: str) -> pd.DataFrame:
    return S3(bucket=bucket).load_csv_to_dataframe(key=s3_key)


def _coerce_assigned_post_ids_to_str_list(
    assigned_post_ids_raw: object, *, user_id: str
) -> list[str]:
    """Parse CSV cell value into list[str]; raise ValueError if shape is wrong."""
    if isinstance(assigned_post_ids_raw, str):
        decoded: object = json.loads(assigned_post_ids_raw)
    elif isinstance(assigned_post_ids_raw, list):
        decoded = assigned_post_ids_raw
    else:
        raise ValueError(
            f"Unexpected assigned_post_ids format: {type(assigned_post_ids_raw)!r} "
            f"for user {user_id!r}"
        )
    if not isinstance(decoded, list):
        raise ValueError(
            f"assigned_post_ids must be a JSON list for user {user_id!r}, "
            f"got {type(decoded).__name__!r}"
        )
    if not all(isinstance(x, str) for x in decoded):
        raise ValueError(f"assigned_post_ids must be a list of strings for user {user_id!r}")
    return decoded


def get_precomputed_assignment(
    user_assignment_record: UserAssignmentRecord, user_assignment_payload: UserAssignmentPayload
):
    precomputed_assignments: pd.DataFrame = load_precomputed_assignments(
        bucket=user_assignment_payload.s3_bucket,
        s3_key=user_assignment_payload.s3_key,
    )
    assignment = precomputed_assignments[
        precomputed_assignments["id"] == user_assignment_payload.assignment_id
    ]
    if assignment.empty:
        raise ValueError(f"Assignment not found for user {user_assignment_record.user_id}")
    assigned_post_ids_raw = assignment.iloc[0]["assigned_post_ids"]
    return _coerce_assigned_post_ids_to_str_list(
        assigned_post_ids_raw, user_id=user_assignment_record.user_id
    )


def main(
    study_id: str,
    study_iteration_id: str,
    prolific_id: str,
    political_party: str,
    assignment_batch_uri: str,
):
    bucket, batch_key_prefix = parse_assignment_batch_uri(assignment_batch_uri)
    s3 = S3(bucket=bucket)
    mirrorview_config = load_batch_config(s3=s3, batch_key_prefix=batch_key_prefix)
    bucket, batch_key_prefix = validate_assignment_batch_uri(
        mirrorview_config,
        assignment_batch_uri,
    )

    user_assignment_record: UserAssignmentRecord = get_or_set_user_assignment_record(
        study_id=study_id,
        study_iteration_id=study_iteration_id,
        prolific_id=prolific_id,
        political_party=political_party,
        mirrorview_config=mirrorview_config,
        batch_key_prefix=batch_key_prefix,
    )

    user_assignment_payload: UserAssignmentPayload = user_assignment_record.payload
    user_assignment_metadata: dict = json.loads(user_assignment_payload.metadata)
    condition = user_assignment_metadata["condition"]

    assigned_post_ids: list[str] = get_precomputed_assignment(
        user_assignment_record=user_assignment_record,
        user_assignment_payload=user_assignment_payload,
    )

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
        assignment_batch_uri=event["assignment_batch_uri"],
    )

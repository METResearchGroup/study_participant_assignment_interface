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
    metadata = {}  # TODO: calculate
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


def get_precomputed_assignment():
    pass


def main(study_id: str, study_iteration_id: str, prolific_id: str, political_party: str):
    # TODO: won't I need political_party to set the assignment if it doesn't
    # exist?
    user_assignment_record: UserAssignmentRecord = get_or_set_user_assignment_record(
        study_id=study_id,
        study_iteration_id=study_iteration_id,
        prolific_id=prolific_id,
        political_party=political_party,
    )
    print(user_assignment_record)

    get_precomputed_assignment()

    return {}


def handler(event, context):
    return {
        "statusCode": 200,
        "body": "Hello, World!",
    }

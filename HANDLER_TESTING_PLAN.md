# Handler Testing Plan

## Goal

Build a robust, fast test strategy for `lambdas/get_study_assignment/handler.py` with:

1. Unit tests for helper functions (everything except `main` by default)
2. Local smoke tests for `handler()` end-to-end orchestration against real AWS resources

Planned files:

- `lambdas/get_study_assignment/tests/test_handler.py`
- `lambdas/get_study_assignment/smoke_tests/local_handler_smoke_test.py`

---

## Why This Split Works

- Unit tests isolate decision logic, retries, payload composition, and edge cases.
- Smoke tests validate integration seams that unit tests mock away (DynamoDB + S3 + serialization + lookup).
- Together, these catch both algorithmic regressions and real environment wiring issues.

---

## Handler Logic Flow (What Must Be Protected)

For `handler(event, context)`:

1. Parse event fields: `study_id`, `study_iteration_id`, `prolific_id`, `political_party`
2. Get existing user assignment record (or create one if missing)
3. Resolve assigned condition from assignment payload metadata
4. Load latest precomputed assignment CSV from S3
5. Locate user assignment row by assignment ID
6. Return interface payload:
   - `assigned_post_ids`
   - `already_assigned=True`
   - `condition`

Critical behavioral guarantees:

- Existing user is idempotent (no duplicate user assignment write)
- New user assignment picks least-populated party-condition cell
- Counter updates are conflict-safe with retry
- Assignment ID and S3 lookup are consistent with party + condition

---

## Unit Test Plan (`lambdas/get_study_assignment/tests/test_handler.py`)

## Scope

Primary target: all helper functions except `main`.

Recommended imports:

- `import lambdas.get_study_assignment.handler as h`
- `pytest`
- `pandas as pd`
- `json`
- `from unittest.mock import MagicMock, patch`

## Test Matrix by Function

### `get_user_assignment_record_if_exists`

- Returns `None` when `get_user_assignment` returns `None`
- Returns record object unchanged when present
- Passes expected args (`study_id`, `study_iteration_id`, `user_id`, table, region)

Suggested tests:

- `test_get_user_assignment_record_if_exists_returns_none`
- `test_get_user_assignment_record_if_exists_returns_record`

### `select_least_assignment_party_condition_key`

- Chooses key with smallest counter
- Tie-breaks deterministically by key name
- Includes missing default keys (`control`, `training`, `training_assisted`) as implicit zero
- Filters out keys that are not for requested party
- Raises if no candidate keys (defensive path)

Suggested tests:

- `test_select_least_key_prefers_smaller_counter`
- `test_select_least_key_tie_breaks_by_key_name`
- `test_select_least_key_adds_missing_default_conditions_with_zero`
- `test_select_least_key_filters_non_matching_party_keys`
- `test_select_least_key_raises_when_no_candidates`

### `assign_user_to_condition`

- Success on first attempt
- Retries after `AssignmentCounterConflictError`
- Raises `RuntimeError` after exhausting `MAX_ASSIGNMENT_RETRIES`
- Returns `{condition, total_in_condition}` shape

Suggested tests:

- `test_assign_user_to_condition_success_first_try`
- `test_assign_user_to_condition_retries_on_conflict_then_succeeds`
- `test_assign_user_to_condition_raises_after_max_retries`

### `get_latest_uploaded_precomputed_assignments_s3_key`

- Filters by exact path suffix `/{party}/{condition}/{OUTPUT_RECORDS_FILENAME}` (not substring `condition in key`, so `training` does not match `training_assisted`)
- Picks latest key by reverse lexical sort
- Raises `ValueError` when no matches exist

Suggested tests:

- `test_get_latest_uploaded_precomputed_assignments_s3_key_returns_latest_match`
- `test_get_latest_uploaded_precomputed_assignments_s3_key_ignores_irrelevant_keys`
- `test_get_latest_uploaded_precomputed_assignments_s3_key_raises_when_no_match`

### `set_user_assignment_record`

- Calls assignment selection + counter path
- Rejects invalid `total_in_condition <= 0`
- Builds `assignment_id` using `generate_single_assignment_id`
- Builds serialized metadata with party + condition
- Calls `put_user_assignment` with expected payload

Suggested tests:

- `test_set_user_assignment_record_persists_expected_payload`
- `test_set_user_assignment_record_raises_on_non_positive_total_in_condition`

### `get_or_set_user_assignment_record`

- Returns existing record without creating new one
- Creates and returns new record if missing

Suggested tests:

- `test_get_or_set_user_assignment_record_returns_existing`
- `test_get_or_set_user_assignment_record_sets_when_missing`

### `load_latest_precomputed_assignments`

- Delegates to `s3.load_csv_to_dataframe` with given key

Suggested test:

- `test_load_latest_precomputed_assignments_delegates_to_s3_loader`

### `get_precomputed_assignment`

- Returns JSON-decoded list when `assigned_post_ids` is string JSON
- Returns list directly when already list
- Raises when assignment id not found in CSV
- Raises on unsupported `assigned_post_ids` type

Suggested tests:

- `test_get_precomputed_assignment_parses_json_string_payload`
- `test_get_precomputed_assignment_accepts_list_payload`
- `test_get_precomputed_assignment_raises_when_assignment_missing`
- `test_get_precomputed_assignment_raises_on_unexpected_payload_type`

### `handler`

- Forwards event fields to `main`
- Returns exactly what `main` returns
- Raises `KeyError` when event is missing required keys (current behavior)

Suggested tests:

- `test_handler_forwards_event_fields_to_main`
- `test_handler_raises_key_error_on_missing_event_field`

## Optional (High-Value) Test for `main`

Even if excluded by policy, adding one orchestration unit test for `main` is high leverage:

- mock `get_or_set_user_assignment_record` + `get_precomputed_assignment`
- assert returned payload shape and condition extraction from metadata

Suggested optional test:

- `test_main_returns_interface_payload_shape`

---

## Smoke Test Plan (`lambdas/get_study_assignment/smoke_tests/local_handler_smoke_test.py`)

## Scope

Validate real integration behavior for `handler()` with:

- DynamoDB tables (`user_assignments`, `study_assignment_counter`)
- S3 precomputed assignment CSV objects
- realistic event payloads

Keep smoke suite small (3-5 tests) and deterministic.

## Test Cases

### 1) New User Happy Path

- Arrange:
  - unique `study_id`, `study_iteration_id`, `prolific_id`
  - upload S3 fixture CSV for all study conditions for target party (`control`, `training`, `training_assisted`)
- Act: call `handler(event, None)`
- Assert:
  - response has `assigned_post_ids` (non-empty list), `already_assigned=True`, `condition in {"control", "training", "training_assisted"}`
  - user assignment row created in DynamoDB

### 2) Existing User Idempotency

- Arrange: same event called twice
- Act: `handler` twice with same user
- Assert:
  - second response semantically equals first
  - no second user assignment row created
  - counter behavior does not imply re-assignment for same user

### 3) Balance Across Conditions (Same Party)

- Arrange: three distinct users in same study/iteration/party; seeded CSVs for all conditions; empty counters
- Act: call handler per user
- Assert:
  - assignments follow `control` → `training` → `training_assisted` when counts are tied (lexicographic key order)
  - least-counter logic after first pass through the three cells

### 4) Party Isolation

- Arrange: one democrat user and one republican user in same study/iteration
- Act: call handler for each
- Assert:
  - each party reads/writes only its own party counter namespace
  - assignment IDs and selected S3 keys match party

### 5) (Optional) Invalid Event Contract

- Act: call `handler` with missing key(s)
- Assert: current error path (`KeyError`) is clear and expected

---

## Smoke Test Harness Design

Follow the same style as `infra/tests/dynamodb_e2e_tests.py`:

- Base class with:
  - `setup()`: load env, create unique IDs, init boto3 table handles, init S3 helper
  - `teardown()`: cleanup DynamoDB rows by iteration prefix and remove S3 fixture objects
- Explicit helper methods:
  - `_seed_precomputed_csv(...)`
  - `_query_user_assignments_for_iteration(...)`
  - `_query_counters_for_iteration(...)`
  - `_cleanup_*`
- Aggregated runner:
  - discover `test_*` methods
  - run `setup -> test -> teardown`
  - print PASS/FAIL summary and non-zero exit code on failure

---

## Data Fixture Guidance

S3 fixture CSV rows should minimally include:

- `id` (must match generated assignment id format like `democrat-control-0001`)
- `assigned_post_ids` (JSON array string, e.g. `["p1","p2"]`)

Store under keys that satisfy handler filtering:

- prefix: `precomputed_assignments/...`
- include party and condition in key path
- end with `assignments.csv`

Because the handler picks latest by reverse lexical sort, fixture key naming should make recency deterministic.

---

## Suggested Commands

Unit tests:

```bash
PYTHONPATH=. uv run pytest lambdas/get_study_assignment/tests/test_handler.py -q
```

Smoke tests:

```bash
PYTHONPATH=. AWS_REGION=us-east-2 USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
uv run python lambdas/get_study_assignment/smoke_tests/local_handler_smoke_test.py
```

Both:

```bash
PYTHONPATH=. uv run pytest lambdas/get_study_assignment/tests/test_handler.py -q && \
PYTHONPATH=. AWS_REGION=us-east-2 USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
uv run python lambdas/get_study_assignment/smoke_tests/local_handler_smoke_test.py
```

---

## Acceptance Criteria

- Unit tests cover all non-`main` functions in `handler.py` and key error paths.
- Smoke tests validate handler happy path + idempotency + balancing + party isolation.
- Smoke test cleanup is reliable (no dangling DynamoDB rows or S3 objects).
- Deterministic outcomes across repeated local runs.

---

## Risks and Mitigations

- Flaky smoke behavior due to shared AWS state  
  - Mitigation: unique `study_id`/`study_iteration_id` per test and strict teardown.
- S3 “latest key” ambiguity  
  - Mitigation: deterministic fixture naming and single expected latest key per case.
- Concurrency race variance in balancing logic  
  - Mitigation: keep smoke tests mostly sequential; test retry logic in unit tests via mocks.

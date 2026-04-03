---
name: ""
overview: ""
todos: []
isProject: false
---

---

name: pr3 dynamodb setup
overview: Plan PR 3 for DynamoDB table setup, helper code, and verification. This plan assumes we keep `lib/dynamodb.py` and include both AWS-backed smoke verification and local automated tests, while staying decoupled from the unmerged PR 1 and PR 2 work.
overview: Plan PR 3 for DynamoDB table setup, helper code, and a single AWS-backed smoke test. This plan assumes we keep `lib/dynamodb.py`, avoid MirrorView-specific models in shared infra code, and stay decoupled from the unmerged PR 1 and PR 2 work.
todos:

- id: freeze-pr3-contracts
content: "Freeze PR 3 contracts: table schema, payload shape, counter semantics, and key serialization before any coding starts."
status: pending
- id: bootstrap-repo-wiring
content: "Update repo wiring for PR 3 prerequisites: add only the Python/AWS dependencies needed for the DynamoDB helper and smoke test."
status: pending
- id: terraform-dynamodb
content: Add Terraform for the two DynamoDB tables in `infra/main.tf` plus table outputs in `infra/outputs.tf`.
status: pending
- id: python-dynamodb-helper
content: Implement `lib/dynamodb.py` helpers for `user_assignments` read/write and atomic `study_assignment_counter` increment.
status: pending
- id: verification-harness
content: Add one AWS-backed smoke test script for read/write, missing-row initialization, and concurrent counter increments.
status: pending
isProject: false

---

# PR 3 Implementation Plan

## Remember

- Exact file paths always
- Exact commands with expected output
- DRY, YAGNI, TDD, frequent commits
- Maximum safely delegable parallelism
- Delegated tasks must be impossible to misread
- `strategy_planning/2026-04-03_v1_system_design.md` is reference-only for PR 3 and must not be edited

## Overview

PR 3 establishes the first durable state layer for the system design in [strategy_planning/2026-04-03_v1_system_design.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/strategy_planning/2026-04-03_v1_system_design.md): Terraform-managed DynamoDB tables, a Python helper layer in [lib/dynamodb.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/dynamodb.py), and one AWS-backed smoke test that proves the intended DynamoDB behavior. Because PRs 1 and 2 are being developed separately, this PR should freeze only the contracts it needs now and keep MirrorView-specific data models out of shared infra code.

## Plan Assets

Store PR-3 planning artifacts under `docs/plans/2026-04-03_pr3_dynamodb_tables_403003/`.
No UI screenshots are required because this PR is infra/backend only.

## Happy Flow

1. Terraform in [infra/main.tf](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/infra/main.tf) and [infra/outputs.tf](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/infra/outputs.tf) creates `user_assignments` and `study_assignment_counter` with the exact primary keys from the strategy doc.
2. Application code in [lib/dynamodb.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/dynamodb.py) exposes helpers to read/write `user_assignments` and atomically increment `study_assignment_counter` using DynamoDB `UpdateItem` with `if_not_exists`.
3. The helper stores `user_assignments.payload` as a JSON string whose `metadata` field is itself a JSON-dumped string, keeping MirrorView-specific structure outside shared infra code.
4. AWS smoke verification in [infra/tests/dynamodb_e2e_tests.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/infra/tests/dynamodb_e2e_tests.py) runs against deployed tables to prove read/write behavior and real counter atomicity under concurrent requests.

## Interface Or Contract Freeze

Lock these decisions before implementation starts:

- Keep the code location exactly as requested: [lib/dynamodb.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/dynamodb.py).
- Treat the later PR-3 key definition in the strategy doc as the logical primary key for `user_assignments`: `(study_id, study_iteration_id, user_id)`.
- Treat the later PR-3 key definition in the strategy doc as the logical primary key for `study_assignment_counter`: `(study_id, study_iteration_id, study_unique_assignment_key)`.
- Freeze the physical DynamoDB schema for `user_assignments` to:
  - partition key: `study_id`
  - sort key: `iteration_user_key`
  - `iteration_user_key = "{study_iteration_id}#{user_id}"`
- Freeze the physical DynamoDB schema for `study_assignment_counter` to:
  - partition key: `study_id`
  - sort key: `iteration_assignment_key`
  - `iteration_assignment_key = "{study_iteration_id}#{study_unique_assignment_key}"`
- Freeze `study_unique_assignment_key` serialization to a deterministic string format, recommended: `"{political_party}:{condition}"`. Do not use tuple reprs like `("democrat", "control")`.
- Freeze counter semantics to 1-based allocation. First successful increment for a missing row returns `1`, second returns `2`, and so on.
- Freeze `user_assignments.payload` as one JSON string stored in DynamoDB. Inside that JSON, `metadata` should be a JSON-dumped string, not a nested object.
- Freeze the payload shape now so PR 4 can depend on it safely:
  - `s3_bucket: str`
  - `s3_key: str`
  - `assignment_id: str`
  - `metadata: str`
- Do not define `AssignmentMetadata` in [lib/dynamodb.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/dynamodb.py). That MirrorView-specific model belongs in [jobs/mirrorview/models.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/jobs/mirrorview/models.py).
- Keep Terraform minimal for PR 3: only [infra/main.tf](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/infra/main.tf) and [infra/outputs.tf](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/infra/outputs.tf).
- Keep verification minimal for PR 3: one AWS-backed smoke script after `terraform apply`; no moto-based tests and no local pytest coverage in this PR.
- Freeze the default AWS region for PR 3 documentation and smoke verification to `us-east-2`.

## Data Models

Define only the shared, storage-oriented models in [lib/dynamodb.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/dynamodb.py) as Pydantic `BaseModel` classes so PR 4 has a stable importable contract:

- `UserAssignmentPayload`
  - `s3_bucket: str`
  - `s3_key: str`
  - `assignment_id: str`
  - `metadata: str`
- `UserAssignmentRecord`
  - `study_id: str`
  - `study_iteration_id: str`
  - `user_id: str`
  - `iteration_user_key: str`
  - `payload: UserAssignmentPayload`
  - `created_at: str`
- `StudyAssignmentCounterRecord`
  - `study_id: str`
  - `study_iteration_id: str`
  - `study_unique_assignment_key: str`
  - `iteration_assignment_key: str`
  - `counter: int`
  - `created_at: str`
  - `last_updated_at: str`

MirrorView-specific domain models, including `AssignmentMetadata`, belong in [jobs/mirrorview/models.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/jobs/mirrorview/models.py), not in [lib/dynamodb.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/dynamodb.py).

Public helpers should accept the logical identifiers and build the physical sort-key strings internally. The helper should treat `metadata` as an opaque JSON string and should not parse MirrorView-specific structure.

## Planned File Structure

PR 3 should leave the repo in this shape:

```text
lib/
    __init__.py
    dynamodb.py
infra/
    main.tf
    outputs.tf
    tests/
        dynamodb_e2e_tests.py
README.md
docs/
    runbook/
        DEPLOY_INFRA.md
pyproject.toml
uv.lock
```

## Serial Coordination Spine

1. Inspect and update repo wiring in [pyproject.toml](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/pyproject.toml).
2. Add the minimum dependencies needed for this PR:
  - runtime: `boto3`, `botocore`
3. Freeze the exact public helper contract that tests will call from [lib/dynamodb.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/dynamodb.py). Recommended functions:
  - `get_user_assignment(...) -> UserAssignmentRecord | None`
  - `put_user_assignment(...) -> UserAssignmentRecord`
  - `increment_assignment_counter(...) -> int`
4. Freeze the exact helper responsibilities:
  - public APIs accept logical identifiers only
  - helper layer constructs `iteration_user_key` and `iteration_assignment_key`
  - helper layer serializes/deserializes `payload`
  - helper layer updates `last_updated_at` on every counter increment
5. Freeze the expected environment variables or CLI args for the AWS smoke script in [infra/tests/dynamodb_e2e_tests.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/infra/tests/dynamodb_e2e_tests.py), for example:
  - `AWS_REGION`
  - `USER_ASSIGNMENTS_TABLE_NAME`
  - `STUDY_ASSIGNMENT_COUNTER_TABLE_NAME`
6. Freeze the deployment documentation outputs:
  - write a runbook in [docs/runbook/DEPLOY_INFRA.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/docs/runbook/DEPLOY_INFRA.md)
  - include AWS CLI setup prerequisites
  - use `us-east-2` in example commands
  - include exact AWS console checks for both DynamoDB tables
7. After those contracts are frozen, parallelize implementation into the packets below.
8. Treat [strategy_planning/2026-04-03_v1_system_design.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/strategy_planning/2026-04-03_v1_system_design.md) as immutable input. PR 3 may cite it, but must not modify it.

## Parallel Task Packets

### Task Packet P1

Objective: add Terraform-managed DynamoDB tables and outputs without touching Python runtime code.
Why parallelizable: once the table contracts are frozen, Terraform files are isolated from the helper and test implementation details.
Files to inspect:

- [strategy_planning/2026-04-03_v1_system_design.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/strategy_planning/2026-04-03_v1_system_design.md)
- [README.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/README.md)
Files allowed to change:
- [infra/main.tf](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/infra/main.tf)
- [infra/outputs.tf](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/infra/outputs.tf)
Files forbidden to change:
- [strategy_planning/2026-04-03_v1_system_design.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/strategy_planning/2026-04-03_v1_system_design.md)
- [lib/dynamodb.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/dynamodb.py)
- [infra/tests/dynamodb_e2e_tests.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/infra/tests/dynamodb_e2e_tests.py)
Preconditions:
- Contract freeze completed.
Dependency tasks:
- `freeze-pr3-contracts`
Required contracts and invariants:
- `user_assignments` must use partition key `study_id` and sort key `iteration_user_key`.
- `study_assignment_counter` must use partition key `study_id` and sort key `iteration_assignment_key`.
- `study_assignment_counter` must support atomic `UpdateItem` increments on `counter`.
- Table names must be output for use by AWS smoke tests and later PRs.
Implementation steps:

1. Create [infra/main.tf](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/infra/main.tf) defining both DynamoDB tables with pay-per-request billing and explicit key attributes:
  - `user_assignments`: `study_id` + `iteration_user_key`
  - `study_assignment_counter`: `study_id` + `iteration_assignment_key`
2. Add `created_at` and `last_updated_at` as plain string attributes in item payloads only; do not try to define them as key attributes in Terraform.
3. Create [infra/outputs.tf](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/infra/outputs.tf) exposing the table names and ARNs.

Verification commands:

- `terraform -chdir=infra fmt -check`
- `terraform -chdir=infra init`
- `terraform -chdir=infra validate`
- `terraform -chdir=infra plan`
Expected outputs:
- `fmt -check` exits `0`
- `validate` prints `Success! The configuration is valid.`
- `plan` shows exactly two DynamoDB tables plus any expected provider bootstrap resources
Done when:
- Both tables exist in Terraform with the correct keys.
- Outputs expose table names needed by scripts/tests.
- `terraform validate` succeeds locally.
Coordinator review checklist:
- Table names match the frozen contract.
- No secondary indexes or extra infra were added without a strategy-doc reason.
- The plan output is minimal and unsurprising.

### Task Packet P2

Objective: implement the Python DynamoDB helper layer in [lib/dynamodb.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/dynamodb.py).
Why parallelizable: the helper module depends only on the frozen schema contract, not on Terraform internals or CI wiring.
Files to inspect:

- [strategy_planning/2026-04-03_v1_system_design.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/strategy_planning/2026-04-03_v1_system_design.md)
- [pyproject.toml](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/pyproject.toml)
- [main.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/main.py)
Files allowed to change:
- [lib/**init**.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/__init__.py)
- [lib/dynamodb.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/dynamodb.py)
Files forbidden to change:
- [strategy_planning/2026-04-03_v1_system_design.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/strategy_planning/2026-04-03_v1_system_design.md)
- [infra/main.tf](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/infra/main.tf)
- [infra/tests/dynamodb_e2e_tests.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/infra/tests/dynamodb_e2e_tests.py)
Preconditions:
- Contract freeze completed.
Dependency tasks:
- `freeze-pr3-contracts`
Required contracts and invariants:
- `get_user_assignment(...)` returns `None` when the row does not exist.
- `put_user_assignment(...)` writes a row keyed by `(study_id, study_iteration_id, user_id)` and returns the normalized stored record.
- `increment_assignment_counter(...)` uses DynamoDB atomic update semantics and returns the updated integer counter.
- The helper must accept table names and standard boto3 configuration so the smoke script can run against real AWS.
- The helper must not define `AssignmentMetadata` or other MirrorView-specific domain models.
- The helper must construct `iteration_user_key` and `iteration_assignment_key` internally so callers never manually format physical keys.
Implementation steps:

1. Add [lib/**init**.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/__init__.py) so `lib` is an importable package.
2. Implement `UserAssignmentPayload`, `UserAssignmentRecord`, and `StudyAssignmentCounterRecord` in [lib/dynamodb.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/dynamodb.py).
3. Implement private key-builder helpers for `iteration_user_key` and `iteration_assignment_key`.
4. Implement typed payload helpers in [lib/dynamodb.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/dynamodb.py) to centralize record serialization/deserialization.
5. Implement `get_user_assignment(...)` with a simple `GetItem`/`Table.get_item` path and a `None` return on missing rows.
6. Implement `put_user_assignment(...)` with explicit `created_at` handling and payload JSON serialization, treating `metadata` as a pre-dumped string.
7. Implement `increment_assignment_counter(...)` with `SET #counter = if_not_exists(#counter, :zero) + :one`, `SET #updated_at = :timestamp`, and `ReturnValues="UPDATED_NEW"`.
8. Normalize the helper return shapes so tests do not need to parse raw DynamoDB wire-format dictionaries.

Verification commands:

- `uv run python -c "from lib.dynamodb import get_user_assignment, put_user_assignment, increment_assignment_counter; print('imports-ok')"`
- `uv run pyright`
Expected outputs:
- The import smoke command prints `imports-ok`
- `pyright` reports `0 errors`
Done when:
- The module can be imported cleanly.
- The helper surface matches the frozen contract.
- No helper returns raw boto3 response blobs as the public API.
Coordinator review checklist:
- Counter increment is truly atomic, not read-then-write in Python.
- Missing-row behavior matches the strategy doc exactly.
- Payload serialization is stable and not double-encoding `metadata`.

### Task Packet P3

Objective: add one real AWS smoke test and one deployment runbook that verify and document PR 3 end to end.
Why parallelizable: after the helper contract is frozen, the smoke script and runbook can be written independently of the Terraform details as long as table names and helper signatures are stable.
Files to inspect:

- [pyproject.toml](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/pyproject.toml)
- [strategy_planning/2026-04-03_v1_system_design.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/strategy_planning/2026-04-03_v1_system_design.md)
Files allowed to change:
- [pyproject.toml](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/pyproject.toml)
- [uv.lock](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/uv.lock)
- [infra/tests/dynamodb_e2e_tests.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/infra/tests/dynamodb_e2e_tests.py)
- [README.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/README.md)
- [docs/runbook/DEPLOY_INFRA.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/docs/runbook/DEPLOY_INFRA.md)
Files forbidden to change:
- [strategy_planning/2026-04-03_v1_system_design.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/strategy_planning/2026-04-03_v1_system_design.md)
- [infra/main.tf](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/infra/main.tf)
- [lib/dynamodb.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/dynamodb.py) except for import-path fixes explicitly requested by the coordinator
Preconditions:
- Contract freeze completed.
Dependency tasks:
- `freeze-pr3-contracts`
- `python-dynamodb-helper`
Required contracts and invariants:
- AWS smoke coverage must exercise real concurrent increments.
- Documentation must tell engineers exactly which commands to run and which environment variables to set.
- The AWS smoke script must verify the frozen physical-key schema indirectly by using only logical identifiers and the public helper functions.
- All example commands should use `us-east-2`.
- The runbook must include AWS CLI setup steps and explicit AWS console checks.
Implementation steps:

1. Add any minimal script/runtime dependencies in [pyproject.toml](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/pyproject.toml) and regenerate [uv.lock](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/uv.lock).
2. Add [infra/tests/dynamodb_e2e_tests.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/infra/tests/dynamodb_e2e_tests.py) as a manually run script that:
  - creates unique test keys
  - verifies read/write on `user_assignments`
  - verifies on-miss increment for `study_assignment_counter`
  - launches concurrent increments for one key and asserts distinct sequential results
  - asserts the first two concurrent results are exactly `1` and `2` for a fresh key
3. Add [docs/runbook/DEPLOY_INFRA.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/docs/runbook/DEPLOY_INFRA.md) with:
  - AWS CLI installation and verification commands
  - AWS credential/profile setup steps needed before running Terraform
  - exact Terraform commands for `init`, `validate`, `plan`, and `apply`
  - exact smoke-test command using `AWS_REGION=us-east-2`
  - exact DynamoDB console checks for `user_assignments` and `study_assignment_counter`
4. Update [README.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/README.md) to link to the runbook instead of duplicating the full deployment instructions.

Verification commands:

- `uv sync --all-groups`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pyright`
- `AWS_REGION=us-east-2 USER_ASSIGNMENTS_TABLE_NAME=user_assignments STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter uv run python infra/tests/dynamodb_e2e_tests.py`
Expected outputs:
- `ruff check`, `ruff format --check`, and `pyright` exit `0`
- The AWS smoke script prints a clear success line after the concurrent increment assertion passes
Done when:
- The AWS smoke script can be run manually against deployed tables.
- [docs/runbook/DEPLOY_INFRA.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/docs/runbook/DEPLOY_INFRA.md) documents exact setup, deploy, smoke-test, and console-verification steps.
- The README links to the runbook.
Coordinator review checklist:
- The AWS smoke test uses unique keys so reruns are safe.
- The smoke test is the only verification harness added in this PR.
- The runbook is specific enough that a teammate can deploy without guessing the AWS CLI setup.

## Integration Order

1. Complete the serial coordination spine and freeze the public contracts.
2. Run P1 and P2 in parallel.
3. Run P3 after P2 lands, because the smoke script depends on the helper signatures.
4. Reconcile final docs and env var names after Terraform outputs and helper APIs are stable.
5. Run lint/type checks, then deploy Terraform, then run the AWS smoke script.

## Manual Verification

- Run `uv sync --all-groups` from [/Users/mark/Documents/work/worktree_study_participant_assignment_interface](/Users/mark/Documents/work/worktree_study_participant_assignment_interface) and confirm dependency resolution succeeds.
- Run `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pyright` and confirm they all exit successfully.
- Run `terraform -chdir=infra init` and `terraform -chdir=infra validate` and confirm Terraform is valid.
- Run `terraform -chdir=infra plan` and confirm the diff contains the two expected DynamoDB tables.
- Apply the infra with the exact environment/account intended for smoke testing.
- Confirm [docs/runbook/DEPLOY_INFRA.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/docs/runbook/DEPLOY_INFRA.md) includes AWS CLI install/setup, Terraform commands, and AWS console checks.
- Run `AWS_REGION=us-east-2 USER_ASSIGNMENTS_TABLE_NAME=<output table name> STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=<output table name> uv run python infra/tests/dynamodb_e2e_tests.py` and confirm the script reports successful read/write and concurrent counter increment checks.
- Open the AWS console and spot-check that the test rows were created with the expected keys and counter values.

## Final Verification

1. Local verification must pass: Ruff, format check, and Pyright.
2. Terraform validation and plan must pass.
3. Real AWS smoke verification must prove that concurrent increments for one `(study_id, study_iteration_id, study_unique_assignment_key)` produce distinct sequential results.
4. The final PR description should explicitly call out the frozen contracts PR 4 can now depend on: payload shape, key serialization, and 1-based counter behavior.

## Alternative Approaches

We chose `lib/dynamodb.py` over a new package directory because you explicitly selected that layout. We chose a single AWS smoke test over local mocked testing because the real requirement here is observable DynamoDB behavior that can be confirmed directly in the AWS console, and you explicitly do not want extra local test scaffolding in this PR.
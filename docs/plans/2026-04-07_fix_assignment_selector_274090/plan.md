---
name: assignment selector fix
overview: Tighten the get-study-assignment S3 selector so it only chooses production timestamp-root batches under `precomputed_assignments/`, and add regression tests that reproduce the real `~handler-smoke/` production failure mode.
todos:
  - id: freeze-selector-contract
    content: Define and document the valid production S3 key contract for precomputed assignments, including timestamp-root filtering and failure behavior when only smoke keys exist.
    status: pending
  - id: implement-selector-filter
    content: Update the Lambda selector helpers in `lambdas/get_study_assignment/handler.py` to ignore non-production roots such as `~handler-smoke/` and choose the latest valid production batch.
    status: pending
  - id: add-regression-tests
    content: Extend `lambdas/get_study_assignment/tests/test_handler.py` with prod-shaped timestamp-path regression tests, including a mixed prod-plus-smoke case and an only-smoke error case.
    status: pending
  - id: verify-targeted-suite
    content: Run the targeted pytest selector tests and confirm the new filtering logic returns the expected production key and raises for smoke-only inputs.
    status: pending
isProject: false
---

# Fix Assignment Selector Regression

## Remember

- Exact file paths always
- Exact commands with expected output
- DRY, YAGNI, TDD, frequent commits
- Maximum safely delegable parallelism
- Delegated tasks must be impossible to misread

## Overview

We will fix the production bug in the get-study-assignment Lambda by changing the S3 key selector in `[lambdas/get_study_assignment/handler.py](lambdas/get_study_assignment/handler.py)` so it only considers production-style batch folders under `precomputed_assignments/<timestamp>/...`. The bug is caused by treating reverse lexical order as a proxy for production recency, which allows `precomputed_assignments/~handler-smoke/...` to outrank real timestamped batches; the plan adds regression tests in `[lambdas/get_study_assignment/tests/test_handler.py](lambdas/get_study_assignment/tests/test_handler.py)` that explicitly model the prod folder layout shown in the bug report.

## Happy Flow

1. The handler assigns a participant to a condition in `[lambdas/get_study_assignment/handler.py](lambdas/get_study_assignment/handler.py)`, then calls `get_latest_uploaded_precomputed_assignments_s3_key()` to choose the assignment CSV for that party and condition.
2. Real uploaded batches are written under `precomputed_assignments/<timestamp>/...` by `[jobs/mirrorview/upload_precomputed_data_to_s3.py](jobs/mirrorview/upload_precomputed_data_to_s3.py)`, where `<timestamp>` matches the production batch folder contract such as `2026_04_07-06:17:02`.
3. The fix introduces a helper that extracts the first folder after `DEFAULT_S3_PREFIX` and accepts it only if it matches the production timestamp contract; keys rooted at `~handler-smoke` or any other ad hoc folder are excluded before the “latest” selection is made.
4. The selector then chooses the newest valid production key for the requested `political_party` and `condition`, preserving the existing party/condition suffix filtering.
5. Unit tests in `[lambdas/get_study_assignment/tests/test_handler.py](lambdas/get_study_assignment/tests/test_handler.py)` verify that a mixed list containing both `~handler-smoke/...` and timestamp-root production keys returns the newest production key, and that a smoke-only list raises a clear `ValueError`.

## Implementation Steps

1. In `[lambdas/get_study_assignment/handler.py](lambdas/get_study_assignment/handler.py)`, add a small helper to extract the first path segment after `DEFAULT_S3_PREFIX`.
2. Add a production-root validator in the same file. Preferred implementation: parse the root with `datetime.strptime(root, "%Y_%m_%d-%H:%M:%S")` so impossible dates are rejected, not just malformed strings. A regex fallback is acceptable if you want to minimize imports.
3. Update `get_latest_uploaded_precomputed_assignments_s3_key()` so it:
  - lists keys under `DEFAULT_S3_PREFIX`
  - filters by party/condition suffix using the existing `_precomputed_assignments_s3_key_matches_party_condition()` helper
  - filters again to valid production-root keys only
  - raises a production-specific `ValueError` if no valid production keys remain
  - returns `sorted(production_keys, reverse=True)[0]` once the candidate set is restricted to timestamp roots
4. In `[lambdas/get_study_assignment/tests/test_handler.py](lambdas/get_study_assignment/tests/test_handler.py)`, add a regression test with keys shaped like prod:
  - `precomputed_assignments/~handler-smoke/local-smoke_2026_04_07-06:27:21_dd44c791/democrat/training/assignments.csv`
  - `precomputed_assignments/2026_04_03-09:36:03/democrat/training/assignments.csv`
  - `precomputed_assignments/2026_04_07-06:17:02/democrat/training/assignments.csv`
   Expected result: the selector returns `precomputed_assignments/2026_04_07-06:17:02/democrat/training/assignments.csv`.
5. Add a second regression test where the only matching key is under `~handler-smoke/...`; expected result: `ValueError` with a message that explicitly says no production precomputed assignment key matched.
6. Update the older selector tests in the same test class to use the real timestamp folder shape `YYYY_MM_DD-HH:MM:SS` instead of `2026-01-03`, so the suite reflects the actual production contract rather than a looser synthetic one.

## Manual Verification

- Run the focused selector test class:
  - Command: `PYTHONPATH=. uv run pytest lambdas/get_study_assignment/tests/test_handler.py -k precomputed_assignments_s3_key`
  - Expected output: all selector-related tests pass, including the new `~handler-smoke` regression coverage.
- Run the full handler unit test file:
  - Command: `PYTHONPATH=. uv run pytest lambdas/get_study_assignment/tests/test_handler.py`
  - Expected output: the test file passes without regressions in unrelated handler behavior.
- Sanity-check the production path contract against the uploader code:
  - Inspect `[jobs/mirrorview/upload_precomputed_data_to_s3.py](jobs/mirrorview/upload_precomputed_data_to_s3.py)`
  - Expected outcome: uploaded batch roots are of the form `precomputed_assignments/<timestamp>/...`, confirming the selector invariant matches the producer.

## Alternative Approaches

We could keep the current broad prefix and try to exclude only `~handler-smoke`, but that is brittle because future ad hoc folders could break selection again. We could also introduce an explicit active-batch manifest in S3 or DynamoDB, which would be more robust long term, but for this targeted bug fix the timestamp-root contract is the smallest safe change because the uploader already enforces that structure.

## Scope Notes

This implementation fixes new selection decisions in the Lambda only. It does not repair any existing persisted `user_assignments` rows that already reference `precomputed_assignments/~handler-smoke/...`; if prod users were written with those payloads, that cleanup should be tracked as a separate operational follow-up.

## Plan Assets

Store any notes or follow-up artifacts for this work in `docs/plans/2026-04-07_fix_assignment_selector_274090/`. No UI screenshots are required because this is a backend-only change.

## Final Verification

Successful completion means:

- `get_latest_uploaded_precomputed_assignments_s3_key()` no longer treats `~handler-smoke` as a production candidate.
- A mixed prod-plus-smoke test reproduces the real bucket structure and passes.
- A smoke-only test fails loudly with a production-specific error.
- Existing handler unit tests still pass.


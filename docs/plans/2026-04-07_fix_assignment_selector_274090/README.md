# Fix assignment selector (plan artifacts)

## Operational follow-up

Lambda selection no longer uses `~handler-smoke/` batch roots. Existing `user_assignments` rows that already reference smoke S3 keys are not migrated by this change.

## Verification

See plan Manual Verification: `PYTHONPATH=. uv run pytest lambdas/get_study_assignment/tests/test_handler.py`.

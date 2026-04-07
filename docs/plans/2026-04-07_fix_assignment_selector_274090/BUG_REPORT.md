# Bug Writeup: Assignment Service Selects Smoke-Test S3 Data Instead of Production Assignments

## Summary

The app failed after political-affiliation selection because the assignment service returned post IDs that do not exist in the app's post catalog. The immediate frontend error was:

```text
Error fetching post assignments: Error: Assignment response contained unknown post IDs: democrat-training-post-1-a, democrat-training-post-1-b
```

This is not a frontend bug. The downstream assignment service selected the wrong `assignments.csv` object from S3. Specifically, it picked a smoke-test dataset under a non-production folder (`~handler-smoke/...`) because it currently chooses the "latest" file by reverse lexical sorting across all matching keys under `precomputed_assignments/`.

Because `~handler-smoke/...` sorts after timestamp folders like `2026_04_07-06:17:02/...`, the smoke-test file wins even though it is not production data.

## What Error We Saw

In the browser, after selecting political affiliation:

```text
Prolific ID: manual-test-3
Loaded 959 posts with mirrors
Political affiliation: democrat | Party group: democrat
Party group for assignment: democrat
Error fetching post assignments: Error: Assignment response contained unknown post IDs: democrat-training-post-1-a, democrat-training-post-1-b
```

The relevant frontend validation is in `public/main.js`. It builds a lookup from the post catalog CSV using `post_primary_key` values, then rejects any assigned IDs that are not present in that catalog.

## Diagnosis

### Frontend expectation

The app loads `img/all_mirrors_claude.csv` and expects assigned IDs to match `post_primary_key` values such as:

- `twitter_0735057d44610df6`
- `reddit_8d728887fb81fa64`
- `bluesky_06489613fbf5ce01`

The browser error showed IDs of the form:

- `democrat-training-post-1-a`
- `democrat-training-post-1-b`

Those are synthetic smoke-test IDs, not real catalog keys.

### Downstream assignment service behavior

The downstream assignment service (`study_participant_assignment_interface`) uses:

- bucket: `jspsych-mirror-view-3`
- prefix: `precomputed_assignments`

Its current "latest file" logic:

1. lists all object keys under `precomputed_assignments/`
2. filters keys by party and condition suffix
3. returns `sorted(relevant_precomputed_keys, reverse=True)[0]`

This is the root cause.

### Live S3 evidence

The bucket currently contains both production-like data and smoke-test data:

- Production-like:
  - `precomputed_assignments/2026_04_07-06:17:02/democrat/training/assignments.csv`
- Smoke-test:
  - `precomputed_assignments/~handler-smoke/local-smoke_2026_04_07-06:27:21_dd44c791/democrat/training/assignments.csv`

The smoke-test file contains exactly the bad IDs seen in the browser:

```csv
id,assigned_post_ids
democrat-training-0001,"[""democrat-training-post-1-a"", ""democrat-training-post-1-b""]"
democrat-training-0002,"[""democrat-training-post-2-a"", ""democrat-training-post-2-b""]"
```

The production-like file contains real post IDs that match the app's catalog:

```csv
id,assigned_post_ids,political_party,condition,created_at
democrat-training-0000,"[""reddit_8d728887fb81fa64"", ... ]",democrat,training,...
```

### Why the wrong file wins

Reverse lexical sorting over these two keys chooses the smoke-test key:

```text
precomputed_assignments/2026_04_07-06:17:02/democrat/training/assignments.csv
precomputed_assignments/~handler-smoke/local-smoke_2026_04_07-06:27:21_dd44c791/democrat/training/assignments.csv
```

Because `~` sorts after digits, the current implementation treats the smoke prefix as "latest".

## Why This Is Definitely the Bug

This was verified from multiple angles:

1. The frontend catalog contains normal production post keys, not synthetic smoke IDs.
2. The frontend validation correctly rejects unknown IDs.
3. The live S3 smoke-test file contains the exact bad IDs seen in the browser.
4. The live S3 production-like file contains real IDs that would satisfy the frontend validation.
5. The downstream service's selection strategy is reverse lexical sorting, which deterministically chooses `~handler-smoke/...` over timestamp folders.
6. The test user that triggered the bug (`manual-test-3`) did not already have a persisted assignment in DynamoDB, so this was not stale cached data.

## Recommended Fix

The selection logic should only consider keys whose first folder under `precomputed_assignments/` is a correctly formatted timestamp folder.

The production folder format is:

```text
YYYY_MM_DD-HH:MM:SS
```

Examples:

- `2026_04_03-09:36:03`
- `2026_04_07-06:17:02`

This is the invariant we should rely on, not whether some other folder name happens to sort earlier or later.

### Correct selection rule

When choosing the "latest" precomputed assignments object:

1. List all keys under `precomputed_assignments/`
2. Filter to keys matching the expected party/condition suffix
3. Further filter to keys whose first path segment after `precomputed_assignments/` matches the timestamp-folder regex
4. Among only those valid production keys, choose the latest timestamp folder

### Suggested timestamp-folder regex

```text
^\d{4}_\d{2}_\d{2}-\d{2}:\d{2}:\d{2}$
```

### Why this is the right invariant

- It is explicit and intentional
- It excludes smoke folders, ad hoc test folders, and any future non-production folder names
- It does not depend on fragile lexical behavior of arbitrary prefixes
- The timestamp format is already sortable, so once filtered, lexical ordering is acceptable

## Concrete Change I Would Make

In the downstream assignment repo, update the function that selects the latest uploaded precomputed assignments key.

Current behavior conceptually:

```python
relevant_precomputed_keys = [
    key for key in precomputed_keys
    if key matches party/condition suffix
]
return sorted(relevant_precomputed_keys, reverse=True)[0]
```

Proposed behavior:

```python
import re

TIMESTAMP_FOLDER_RE = re.compile(r"^\d{4}_\d{2}_\d{2}-\d{2}:\d{2}:\d{2}$")

def _extract_root_folder_after_prefix(key: str, prefix: str) -> str | None:
    normalized_prefix = prefix.rstrip("/") + "/"
    if not key.startswith(normalized_prefix):
        return None
    remainder = key[len(normalized_prefix):]
    parts = remainder.split("/", 1)
    return parts[0] if parts else None

def _is_timestamped_production_key(key: str, prefix: str) -> bool:
    folder = _extract_root_folder_after_prefix(key, prefix)
    return bool(folder and TIMESTAMP_FOLDER_RE.fullmatch(folder))

relevant_precomputed_keys = [
    key for key in precomputed_keys
    if _precomputed_assignments_s3_key_matches_party_condition(
        key, political_party=political_party, condition=condition
    )
]

production_keys = [
    key for key in relevant_precomputed_keys
    if _is_timestamped_production_key(key, DEFAULT_S3_PREFIX)
]

if not production_keys:
    raise ValueError(
        f"No production precomputed assignment S3 object keys match "
        f"political_party={political_party!r}, condition={condition!r}"
    )

return sorted(production_keys, reverse=True)[0]
```

## Additional Operational Cleanup

Even after the code fix, the smoke-test data currently sitting under:

- `precomputed_assignments/~handler-smoke/...`

is risky because it lives under the same broad production prefix. I would also recommend one of:

1. move smoke-test objects out of `precomputed_assignments/`
2. delete those smoke-test objects if no longer needed
3. store smoke data under a separate prefix entirely

The code fix is still necessary, because relying on path naming discipline alone is too brittle.

## Expected Outcome After Fix

After the downstream selector is fixed:

- the assignment service will return real `post_primary_key` values from the timestamped production dataset
- the frontend validation in `public/main.js` will pass
- the app will proceed past political-affiliation selection normally

## Scope of Fix

This bug should be fixed in the downstream assignment service / repo, not in the frontend and not in `lambda-get-post-assignments.mjs`.

The frontend behavior is correct: it caught a genuine contract/data mismatch and surfaced it early.

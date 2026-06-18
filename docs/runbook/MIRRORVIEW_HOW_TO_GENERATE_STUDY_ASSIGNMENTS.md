# How to generate study assignments for MirrorView

## High level steps

1. Upload flipped posts.
2. Choose a YAML config under `jobs/mirrorview/config/`.
3. Generate the precomputed assignments (`jobs/mirrorview/precompute_assignments.py`).
4. Validate the precomputed assignments (`jobs/mirrorview/validate_precomputed_assignments.py`).
5. Upload the batch to S3 (`jobs/mirrorview/upload_precomputed_data_to_s3.py`).
6. Invoke `get_study_assignment` with the uploaded batch URI.

## Specific steps

1. Upload flipped posts.
2. Choose a YAML config under `jobs/mirrorview/config/`:
   - `default.yaml` — 2 parties × 3 conditions, 1,000 rows per cell, bucket `jspsych-mirror-view-3`
   - `mirrorview_scaled.yaml` — 2 parties × `training_assisted` only, 25,000 rows per cell, bucket `jspsych-mirror-view-4`
3. Precompute assignments (writes under `data/mirrorview/<timestamp>/`):

```bash
PYTHONPATH=. uv run python -m jobs.mirrorview.precompute_assignments \
  --config jobs/mirrorview/config/default.yaml
```

For the scaled production batch:

```bash
PYTHONPATH=. uv run python -m jobs.mirrorview.precompute_assignments \
  --config jobs/mirrorview/config/mirrorview_scaled.yaml
```

4. Validate the generated batch:

```bash
PYTHONPATH=. uv run python -m jobs.mirrorview.validate_precomputed_assignments \
  --config jobs/mirrorview/config/default.yaml \
  --path data/mirrorview/<timestamp>
```

Or for the larger collection batch:

```bash
PYTHONPATH=. uv run python -m jobs.mirrorview.validate_precomputed_assignments \
  --config jobs/mirrorview/config/mirrorview_scaled.yaml \
  --path data/mirrorview/<timestamp>
```

Use the same `--config` as precompute. Expected output ends with `All checks passed for ...`.

5. Upload CSVs plus the exact config file as `config.yaml` in the S3 batch root:

```bash
PYTHONPATH=. uv run python -m jobs.mirrorview.upload_precomputed_data_to_s3 \
  --config jobs/mirrorview/config/mirrorview_scaled.yaml \
  --path data/mirrorview/<timestamp>
```

Expected S3 layout for a scaled batch:

```text
s3://jspsych-mirror-view-4/precomputed_assignments/<timestamp>/config.yaml
s3://jspsych-mirror-view-4/precomputed_assignments/<timestamp>/democrat/training_assisted/assignments.csv
s3://jspsych-mirror-view-4/precomputed_assignments/<timestamp>/republican/training_assisted/assignments.csv
```

6. Invoke `get_study_assignment` with `assignment_batch_uri` pointing at the uploaded batch, for example:

```json
{
  "study_id": "mirrorview",
  "study_iteration_id": "scaled_2026_06",
  "prolific_id": "abc123",
  "political_party": "democrat",
  "assignment_batch_uri": "s3://jspsych-mirror-view-4/precomputed_assignments/<timestamp>"
}
```

The Lambda loads `config.yaml` from that batch, validates the URI against the config, and assigns only across configured conditions.

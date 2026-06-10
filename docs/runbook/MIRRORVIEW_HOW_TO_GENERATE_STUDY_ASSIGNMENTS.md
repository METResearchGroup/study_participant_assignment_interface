# How to generate study assignments for MirrorView

1. Upload flipped posts.
2. Run `scripts/create_curated_mirrored_posts.py` that returns a .csv file with fields `post_primary_key`, `sampled_stance`, and `sample_toxicity_type`.
3. Choose a YAML config under `jobs/mirrorview/config/`:
   - `default.yaml` — 2 parties × 3 conditions, 1,000 rows per cell, bucket `jspsych-mirror-view-3`
   - `mirrorview_scaled.yaml` — 2 parties × `training_assisted` only, 25,000 rows per cell, bucket `jspsych-mirror-view-4`
4. Precompute assignments (writes under `data/mirrorview/<timestamp>/`):

```bash
PYTHONPATH=. uv run python -m jobs.mirrorview.precompute_assignments \
  --config jobs/mirrorview/config/default.yaml
```

For the scaled production batch:

```bash
PYTHONPATH=. uv run python -m jobs.mirrorview.precompute_assignments \
  --config jobs/mirrorview/config/mirrorview_scaled.yaml
```

5. Validate the generated batch:

```bash
PYTHONPATH=. uv run python -m jobs.mirrorview.validate_precomputed_assignments \
  --config jobs/mirrorview/config/default.yaml \
  --path data/mirrorview/<timestamp>
```

Use the same `--config` as precompute. Expected output ends with `All checks passed for ...`.

6. Upload CSVs plus the exact config file as `config.yaml` in the S3 batch root:

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

7. Invoke `get_study_assignment` with `assignment_batch_uri` pointing at the uploaded batch, for example:

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

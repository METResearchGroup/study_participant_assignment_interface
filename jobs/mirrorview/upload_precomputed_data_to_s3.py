"""Upload a local MirrorView precompute batch directory to S3.

Layout under `precomputed_assignments/<iteration>/`:

    democrat/control/assignments.csv
    democrat/training_assisted/assignments.csv
    ...

    PYTHONPATH=. uv run python -m jobs.mirrorview.upload_precomputed_data_to_s3 \
        --path data/mirrorview/2026_04_03-09:36:03
"""

from __future__ import annotations

import argparse
from pathlib import Path

from lib.constants import ROOT_DIR
from lib.s3 import S3

DEFAULT_BUCKET = "jspsych-mirror-view-3"
DEFAULT_S3_PREFIX = "precomputed_assignments"
LOCAL_DATA_PREFIX = ROOT_DIR / "data" / "mirrorview"


def _iter_files(batch_root: Path) -> list[Path]:
    files = sorted(p for p in batch_root.rglob("*") if p.is_file())
    return [p for p in files if p.suffix.lower() == ".csv"]


def _validate_local_path(local_path: Path) -> None:
    if not local_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {local_path}")
    if not local_path.exists():
        raise FileNotFoundError(f"Directory does not exist: {local_path}")
    # Check if the provided local_path starts with LOCAL_DATA_PREFIX
    local_path_str = str(local_path.resolve())
    local_data_prefix_str = str(LOCAL_DATA_PREFIX.resolve())
    if not local_path_str.startswith(local_data_prefix_str):
        raise ValueError(f"Path {local_path_str} does not start with {local_data_prefix_str}")


def upload_batch(local_batch_dir: Path) -> None:
    _validate_local_path(local_batch_dir)
    files = _iter_files(local_batch_dir)
    bucket = DEFAULT_BUCKET
    store = S3(bucket=bucket)

    # Extract the path part after LOCAL_DATA_PREFIX for S3 key prefixing
    timestamp_dir = str(local_batch_dir.relative_to(LOCAL_DATA_PREFIX))

    s3_base_prefix = f"{DEFAULT_S3_PREFIX}/{timestamp_dir}"

    for path in files:
        # grabs, e.g., 'democrat/control/assignments.csv'
        relative_fp: str = str(path.relative_to(local_batch_dir))
        key: str = f"{s3_base_prefix}/{relative_fp}"
        print(f"Uploading {relative_fp} -> s3://{bucket}/{key}")
        store.upload_file(path, key)

    print(f"Uploaded {len(files)} objects under s3://{bucket}/{s3_base_prefix}/")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload a local data/mirrorview/<timestamp>/ batch to S3.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        required=True,
        help="Local batch root (e.g. data/mirrorview/2026_04_03-09:36:03).",
    )
    args = parser.parse_args()

    local_batch_dir = args.path.expanduser().resolve()

    upload_batch(local_batch_dir=local_batch_dir)


if __name__ == "__main__":
    main()

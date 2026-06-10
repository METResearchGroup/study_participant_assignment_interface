"""Upload a local MirrorView precompute batch directory to S3.

Layout under `precomputed_assignments/<iteration>/`:

    config.yaml
    democrat/control/assignments.csv
    democrat/training_assisted/assignments.csv
    ...

    PYTHONPATH=. uv run python -m jobs.mirrorview.upload_precomputed_data_to_s3 \\
        --config jobs/mirrorview/config/default.yaml \\
        --path data/mirrorview/2026_04_03-09:36:03
"""

from __future__ import annotations

import argparse
from pathlib import Path

from jobs.mirrorview.config_loader import (
    MirrorViewConfig,
    load_mirrorview_config,
    resolve_repo_path,
)
from lib.s3 import S3


def _validate_local_path(local_path: Path, *, local_data_root: Path) -> None:
    if not local_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {local_path}")
    if not local_path.exists():
        raise FileNotFoundError(f"Directory does not exist: {local_path}")
    local_path_str = str(local_path.resolve())
    local_data_prefix_str = str(local_data_root.resolve())
    if not local_path_str.startswith(local_data_prefix_str):
        raise ValueError(f"Path {local_path_str} does not start with {local_data_prefix_str}")


def _validate_expected_csvs_exist(local_batch_dir: Path, config: MirrorViewConfig) -> None:
    missing: list[str] = []
    for relative_path in config.expected_relative_csv_paths():
        if not (local_batch_dir / relative_path).is_file():
            missing.append(relative_path)
    if missing:
        raise FileNotFoundError(
            f"Missing configured assignment CSVs under {local_batch_dir}: {missing}"
        )


def upload_batch(
    local_batch_dir: Path,
    *,
    config: MirrorViewConfig,
    config_source_path: Path,
) -> None:
    local_data_root = resolve_repo_path(config.local_data_dir)
    _validate_local_path(local_batch_dir, local_data_root=local_data_root)
    _validate_expected_csvs_exist(local_batch_dir, config)

    bucket = config.s3.bucket
    store = S3(bucket=bucket)

    timestamp_dir = str(local_batch_dir.relative_to(local_data_root))
    s3_base_prefix = f"{config.s3.prefix.rstrip('/')}/{timestamp_dir}"

    for relative_path in config.expected_relative_csv_paths():
        path = local_batch_dir / relative_path
        key = f"{s3_base_prefix}/{relative_path}"
        print(f"Uploading {relative_path} -> s3://{bucket}/{key}")
        store.upload_file(path, key)

    config_key = f"{s3_base_prefix}/config.yaml"
    print(f"Uploading config.yaml -> s3://{bucket}/{config_key}")
    store.upload_file(config_source_path, config_key, content_type="application/x-yaml")

    print(
        f"Uploaded {len(config.expected_relative_csv_paths())} CSV objects and config.yaml "
        f"under s3://{bucket}/{s3_base_prefix}/"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload a local data/mirrorview/<timestamp>/ batch to S3.",
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to MirrorView YAML config (e.g. jobs/mirrorview/config/default.yaml).",
    )
    parser.add_argument(
        "--path",
        type=Path,
        required=True,
        help="Local batch root (e.g. data/mirrorview/2026_04_03-09:36:03).",
    )
    args = parser.parse_args()

    config = load_mirrorview_config(args.config)
    config_source_path = resolve_repo_path(args.config)
    local_batch_dir = resolve_repo_path(args.path)

    upload_batch(
        local_batch_dir=local_batch_dir,
        config=config,
        config_source_path=config_source_path,
    )


if __name__ == "__main__":
    main()

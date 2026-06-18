from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from jobs.mirrorview.config_loader import (
    MirrorViewConfig,
    load_mirrorview_config,
    resolve_repo_path,
    validate_assignment_batch_uri,
)
from lib.constants import ROOT_DIR


def test_default_config_parses_and_expands_six_cells() -> None:
    config = load_mirrorview_config(ROOT_DIR / "jobs/mirrorview/config/default.yaml")
    cells = list(config.iter_cells())
    assert len(cells) == 6
    assert all(count == 1000 for _party, _condition, count in cells)
    assert config.s3.bucket == "jspsych-mirror-view-3"


def test_scaled_config_parses_two_cells_with_25000_rows() -> None:
    config = load_mirrorview_config(ROOT_DIR / "jobs/mirrorview/config/mirrorview_scaled.yaml")
    cells = list(config.iter_cells())
    assert cells == [
        ("democrat", "training_assisted", 25000),
        ("republican", "training_assisted", 25000),
    ]
    assert config.input_posts_path == (
        "jobs/mirrorview/flip_datasets/mirrorview_scaled_2026_06_18/flips.csv"
    )
    assert config.expected_total_unique_posts == 10000
    assert config.expected_min_assignments_per_post == 3


def test_expected_relative_csv_paths_for_scaled_config() -> None:
    config = load_mirrorview_config(ROOT_DIR / "jobs/mirrorview/config/mirrorview_scaled.yaml")
    assert config.expected_relative_csv_paths() == [
        "democrat/training_assisted/assignments.csv",
        "republican/training_assisted/assignments.csv",
    ]


def test_resolve_repo_path_relative_to_repo_root() -> None:
    resolved = resolve_repo_path("jobs/mirrorview/config/default.yaml")
    assert resolved == (ROOT_DIR / "jobs/mirrorview/config/default.yaml").resolve()


def test_explicit_cells_config(tmp_path: Path) -> None:
    config_path = tmp_path / "cells.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "name": "explicit",
                "input_posts_path": "jobs/mirrorview/all_mirrors_claude.csv",
                "s3": {"bucket": "example-bucket", "prefix": "precomputed_assignments"},
                "cells": [
                    {"political_party": "democrat", "condition": "control", "count": 10},
                    {"political_party": "republican", "condition": "training", "count": 20},
                ],
            }
        )
    )
    config = load_mirrorview_config(config_path)
    assert list(config.iter_cells()) == [
        ("democrat", "control", 10),
        ("republican", "training", 20),
    ]


@pytest.mark.parametrize(
    "raw_config,match",
    [
        (
            {
                "name": "missing_cells",
                "input_posts_path": "jobs/mirrorview/all_mirrors_claude.csv",
                "s3": {"bucket": "example-bucket"},
            },
            "parties, conditions, and assignments_per_cell",
        ),
        (
            {
                "name": "both_specs",
                "input_posts_path": "jobs/mirrorview/all_mirrors_claude.csv",
                "s3": {"bucket": "example-bucket"},
                "parties": ["democrat"],
                "conditions": ["control"],
                "assignments_per_cell": 1,
                "cells": [{"political_party": "democrat", "condition": "control", "count": 1}],
            },
            "not both",
        ),
    ],
)
def test_invalid_configs_fail(raw_config: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        MirrorViewConfig.model_validate(raw_config)


def test_validate_assignment_batch_uri_accepts_matching_uri() -> None:
    config = load_mirrorview_config(ROOT_DIR / "jobs/mirrorview/config/mirrorview_scaled.yaml")
    bucket, prefix = validate_assignment_batch_uri(
        config,
        "s3://jspsych-mirror-view-4/precomputed_assignments/2026_06_10-15:00:00",
    )
    assert bucket == "jspsych-mirror-view-4"
    assert prefix == "precomputed_assignments/2026_06_10-15:00:00"


def test_validate_assignment_batch_uri_rejects_bucket_mismatch() -> None:
    config = load_mirrorview_config(ROOT_DIR / "jobs/mirrorview/config/mirrorview_scaled.yaml")
    with pytest.raises(ValueError, match="bucket"):
        validate_assignment_batch_uri(
            config,
            "s3://jspsych-mirror-view-3/precomputed_assignments/2026_06_10-15:00:00",
        )

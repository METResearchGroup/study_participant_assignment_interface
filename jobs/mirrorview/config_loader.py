from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

from jobs.mirrorview.constants import OUTPUT_RECORDS_FILENAME
from lib.constants import ROOT_DIR


class S3Config(BaseModel):
    bucket: str
    prefix: str = "precomputed_assignments"


class AssignmentCell(BaseModel):
    political_party: str
    condition: str
    count: int


class MirrorViewConfig(BaseModel):
    name: str
    input_posts_path: str
    local_data_dir: str = "data/mirrorview"
    random_seed: int = 42
    s3: S3Config
    parties: list[str] | None = None
    conditions: list[str] | None = None
    assignments_per_cell: int | None = None
    cells: list[AssignmentCell] | None = None

    @model_validator(mode="after")
    def validate_cell_spec(self) -> MirrorViewConfig:
        has_cartesian = (
            self.parties is not None
            and self.conditions is not None
            and self.assignments_per_cell is not None
        )
        has_explicit = self.cells is not None and len(self.cells) > 0
        if has_cartesian and has_explicit:
            raise ValueError(
                "Provide either parties/conditions/assignments_per_cell or cells, not both"
            )
        if not has_cartesian and not has_explicit:
            raise ValueError(
                "Config must provide parties, conditions, and assignments_per_cell, "
                "or explicit cells"
            )
        return self

    def iter_cells(self) -> Iterator[tuple[str, str, int]]:
        if self.cells:
            for cell in self.cells:
                yield cell.political_party, cell.condition, cell.count
        else:
            assert self.parties is not None
            assert self.conditions is not None
            assert self.assignments_per_cell is not None
            for party in self.parties:
                for condition in self.conditions:
                    yield party, condition, self.assignments_per_cell

    def expected_relative_csv_paths(self) -> list[str]:
        return [
            f"{party}/{condition}/{OUTPUT_RECORDS_FILENAME}"
            for party, condition, _count in self.iter_cells()
        ]

    def configured_conditions(self) -> tuple[str, ...]:
        if self.conditions is not None:
            return tuple(self.conditions)
        return tuple(sorted({condition for _party, condition, _count in self.iter_cells()}))


def resolve_repo_path(path: Path | str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.resolve()
    return (ROOT_DIR / candidate).resolve()


def load_mirrorview_config(path: Path | str) -> MirrorViewConfig:
    config_path = resolve_repo_path(path)
    raw = yaml.safe_load(config_path.read_text())
    return MirrorViewConfig.model_validate(raw)


def parse_assignment_batch_uri(assignment_batch_uri: str) -> tuple[str, str]:
    """Parse s3://bucket/prefix/timestamp into bucket and batch key prefix."""
    if not assignment_batch_uri.startswith("s3://"):
        raise ValueError(
            f"assignment_batch_uri must start with s3://, got {assignment_batch_uri!r}"
        )
    without_scheme = assignment_batch_uri.removeprefix("s3://")
    bucket, _, key_prefix = without_scheme.partition("/")
    if not bucket or not key_prefix:
        raise ValueError(
            f"assignment_batch_uri must include bucket and key prefix: {assignment_batch_uri!r}"
        )
    return bucket, key_prefix.rstrip("/")


def validate_assignment_batch_uri(
    config: MirrorViewConfig,
    assignment_batch_uri: str,
) -> tuple[str, str]:
    """Parse URI and verify bucket/prefix match config. Returns (bucket, batch_key_prefix)."""
    bucket, batch_key_prefix = parse_assignment_batch_uri(assignment_batch_uri)
    if bucket != config.s3.bucket:
        raise ValueError(
            f"assignment_batch_uri bucket {bucket!r} does not match "
            f"config s3.bucket {config.s3.bucket!r}"
        )
    expected_prefix = config.s3.prefix.rstrip("/")
    prefix_matches = batch_key_prefix == expected_prefix or batch_key_prefix.startswith(
        f"{expected_prefix}/"
    )
    if not prefix_matches:
        raise ValueError(
            f"assignment_batch_uri prefix {batch_key_prefix!r} does not match "
            f"config s3.prefix {expected_prefix!r}"
        )
    return bucket, batch_key_prefix

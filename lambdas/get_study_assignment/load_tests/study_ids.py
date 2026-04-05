"""Study ID and iteration ID helpers for load tests."""

from __future__ import annotations

import re
from uuid import uuid4

from lib.timestamp_utils import get_current_timestamp

DEFAULT_STUDY_ID = "dev_jspsych-pilot-3"
DEFAULT_ITERATION_PREFIX = "load"
_NON_SLUG_CHARS = re.compile(r"[^a-z0-9\-]+")


def _slugify(value: str) -> str:
    value = value.lower().replace("_", "-").replace(":", "-")
    value = _NON_SLUG_CHARS.sub("-", value)
    return value.strip("-")


def make_study_iteration_id(prefix: str = DEFAULT_ITERATION_PREFIX) -> str:
    """Create a fresh, traceable study iteration id for one load run."""
    timestamp = _slugify(get_current_timestamp())
    suffix = uuid4().hex[:8]
    return f"{prefix}_{timestamp}_{suffix}"


def make_iteration_slug(study_iteration_id: str) -> str:
    """Derive a safe slug used in synthetic prolific IDs."""
    return _slugify(study_iteration_id)

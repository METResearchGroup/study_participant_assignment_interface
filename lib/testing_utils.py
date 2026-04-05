"""Shared helpers for manual smoke / e2e test scripts."""

from __future__ import annotations

import os
from typing import Any


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}. Expected {expected!r}, got {actual!r}")

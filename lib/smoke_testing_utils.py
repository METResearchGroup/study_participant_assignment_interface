"""Shared helpers for script-style smoke tests (setup / test_* / teardown)."""

from __future__ import annotations

import traceback
from collections.abc import Sequence
from typing import Any


def iter_smoke_test_methods(test_instance: Any) -> list[str]:
    """Return sorted `test_*` callable names on the instance."""
    methods = [
        name
        for name in dir(test_instance)
        if name.startswith("test_") and callable(getattr(test_instance, name))
    ]
    return sorted(methods)


def run_smoke_tests(test_classes: Sequence[type[Any]]) -> int:
    """Run all smoke tests with setup/teardown and aggregated reporting.

    Algorithm:
    1. For each test class, instantiate it and discover `test_*` methods.
    2. For each method, run `setup()` -> test method -> `teardown()` in a
       try/finally block so cleanup runs even on failure.
    3. Track failures by fully qualified name and print a summary.

    Returns 0 if every method and teardown succeeded, else 1.
    """
    failed: set[str] = set()
    total_methods = sum(len(iter_smoke_test_methods(cls())) for cls in test_classes)
    for test_class in test_classes:
        test_instance = test_class()
        for method_name in iter_smoke_test_methods(test_instance):
            test_label = f"{test_class.__name__}.{method_name}"
            try:
                test_instance.setup()
                getattr(test_instance, method_name)()
                print(f"PASS {test_label}")
            except Exception as exc:
                failed.add(test_label)
                print(f"FAIL {test_label}: {exc}")
                traceback.print_exc()
            finally:
                try:
                    test_instance.teardown()
                except Exception as exc:
                    failed.add(test_label)
                    print(f"FAIL {test_label} (teardown): {exc}")
                    traceback.print_exc()

    passed_count = total_methods - len(failed)
    print(f"Summary: {passed_count} passed, {len(failed)} failed")
    return 1 if failed else 0

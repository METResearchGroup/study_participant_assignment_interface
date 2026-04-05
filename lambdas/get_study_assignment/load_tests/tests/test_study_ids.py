from __future__ import annotations

import re

from lambdas.get_study_assignment.load_tests import study_ids


def test_make_study_iteration_id_uses_timestamp_and_suffix(monkeypatch) -> None:
    monkeypatch.setattr(study_ids, "get_current_timestamp", lambda: "2026_04_05-11:22:33")
    value = study_ids.make_study_iteration_id(prefix="dev")
    assert value.startswith("dev_2026-04-05-11-22-33_")
    assert re.match(r"^dev_2026-04-05-11-22-33_[0-9a-f]{8}$", value)


def test_make_iteration_slug_normalizes_special_chars() -> None:
    slug = study_ids.make_iteration_slug("Load_ABC:2026/04/05")
    assert slug == "load-abc-2026-04-05"

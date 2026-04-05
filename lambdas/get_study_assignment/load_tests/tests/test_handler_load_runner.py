from __future__ import annotations

from pathlib import Path

import pandas as pd

from lambdas.get_study_assignment.load_tests.handler_load_runner import (
    LoadRunnerConfig,
    run_handler_load,
)


def _build_ground_truth() -> tuple[pd.DataFrame, list[str]]:
    rows: list[dict[str, str]] = []
    post_ids: list[str] = []
    i = 0

    def add(n: int, stance: str, tox: str) -> None:
        nonlocal i
        for _ in range(n):
            pid = f"post-{i:03d}"
            i += 1
            post_ids.append(pid)
            rows.append(
                {
                    "post_primary_key": pid,
                    "sampled_stance": stance,
                    "sample_toxicity_type": tox,
                }
            )

    add(3, "left", "sample_low_toxicity")
    add(2, "right", "sample_low_toxicity")
    add(5, "left", "sample_middle_toxicity")
    add(5, "right", "sample_middle_toxicity")
    add(2, "left", "sample_high_toxicity")
    add(3, "right", "sample_high_toxicity")
    return pd.DataFrame(rows).set_index("post_primary_key"), post_ids


class FakeInvoker:
    backend_name = "fake"

    def __init__(self, post_ids: list[str]) -> None:
        self._post_ids = post_ids
        self._counts: dict[str, int] = {"democrat": 0, "republican": 0}

    def invoke(self, event):
        party = str(event["political_party"])
        self._counts[party] += 1
        # Alternate condition within each party to keep request x condition balanced.
        condition = "control" if self._counts[party] % 2 == 1 else "training_assisted"
        return {
            "assigned_post_ids": list(self._post_ids),
            "already_assigned": True,
            "condition": condition,
        }


def test_run_handler_load_fake_invoker_n5(monkeypatch, tmp_path: Path) -> None:
    ground_truth, post_ids = _build_ground_truth()
    monkeypatch.setattr(
        "lambdas.get_study_assignment.load_tests.handler_load_runner.load_ground_truth_post_pool",
        lambda: ground_truth,
    )
    config = LoadRunnerConfig(
        invoker=FakeInvoker(post_ids),
        backend="fake",
        users=5,
        scenario="random",
        ramp_seconds=0.1,
        max_workers=4,
        report_dir=tmp_path,
        cleanup_after=False,
    )
    result = run_handler_load(config, cleanup_ctx=None)
    assert result.exit_code == 0
    assert result.summary["users_requested"] == 5
    assert result.summary["users_succeeded"] == 5
    assert result.summary["hard_failures"] == 0
    assert result.summary["invariant_violations"] == 0

    summary_path = tmp_path / "summary.json"
    outcomes_path = tmp_path / "outcomes.csv"
    assert summary_path.is_file()
    assert outcomes_path.is_file()

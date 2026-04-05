"""Threaded load-test runner for get_study_assignment."""

from __future__ import annotations

import csv
import json
import os
import threading
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from jobs.mirrorview.constants import DEFAULT_BUCKET, DEFAULT_S3_PREFIX
from lambdas.get_study_assignment.load_tests.distribution_assertions import (
    DistributionCheckResult,
    assert_distribution,
)
from lambdas.get_study_assignment.load_tests.metrics import summarize_ms
from lambdas.get_study_assignment.load_tests.post_invariants import (
    PostInvariantResult,
    load_ground_truth_post_pool,
    validate_handler_assigned_post_ids,
)
from lambdas.get_study_assignment.load_tests.ramp import stagger_seconds
from lambdas.get_study_assignment.load_tests.study_ids import (
    DEFAULT_STUDY_ID,
    make_iteration_slug,
    make_study_iteration_id,
)
from lambdas.get_study_assignment.load_tests.traffic import parties_for_run
from lambdas.get_study_assignment.smoke_tests.handler_invokers import HandlerInvoker


@dataclass(frozen=True)
class LoadRunnerConfig:
    invoker: HandlerInvoker
    backend: str
    users: int
    scenario: str
    ramp_seconds: float
    max_workers: int
    study_id: str = DEFAULT_STUDY_ID
    study_iteration_id: str | None = None
    seed: int = 42
    report_dir: Path | None = None
    cleanup_after: bool = True


@dataclass(frozen=True)
class CleanupContext:
    region_name: str
    user_assignments_table_name: str
    assignment_counter_table_name: str
    bucket_name: str = DEFAULT_BUCKET


@dataclass(frozen=True)
class WorkerOutcome:
    index: int
    party: str
    condition: str | None
    assigned_post_ids: list[str] | None
    latency_ms: float | None
    hard_failure: bool
    error: str | None
    skipped: bool = False


@dataclass(frozen=True)
class LoadRunResult:
    exit_code: int
    summary: dict[str, Any]


def _make_event(
    *, study_id: str, study_iteration_id: str, prolific_id: str, political_party: str
) -> dict[str, str]:
    return {
        "study_id": study_id,
        "study_iteration_id": study_iteration_id,
        "prolific_id": prolific_id,
        "political_party": political_party,
    }


def _worker_invoke(
    *,
    index: int,
    party: str,
    scheduled_offset_seconds: float,
    t0: float,
    stop_event: threading.Event,
    invoker: HandlerInvoker,
    study_id: str,
    study_iteration_id: str,
    iteration_slug: str,
) -> WorkerOutcome:
    now = time.perf_counter()
    wake_up_at = t0 + scheduled_offset_seconds
    if wake_up_at > now:
        time.sleep(wake_up_at - now)

    if stop_event.is_set():
        return WorkerOutcome(
            index=index,
            party=party,
            condition=None,
            assigned_post_ids=None,
            latency_ms=None,
            hard_failure=False,
            error=None,
            skipped=True,
        )

    event = _make_event(
        study_id=study_id,
        study_iteration_id=study_iteration_id,
        prolific_id=f"load-{iteration_slug}-{index:05d}",
        political_party=party,
    )
    started = time.perf_counter()
    try:
        payload = invoker.invoke(event)
    except Exception as exc:
        return WorkerOutcome(
            index=index,
            party=party,
            condition=None,
            assigned_post_ids=None,
            latency_ms=None,
            hard_failure=True,
            error=f"invoke failed: {exc}",
        )
    duration_ms = (time.perf_counter() - started) * 1000.0

    if not isinstance(payload, dict):
        return WorkerOutcome(
            index=index,
            party=party,
            condition=None,
            assigned_post_ids=None,
            latency_ms=None,
            hard_failure=True,
            error=f"expected dict response, got {type(payload)!r}",
        )
    condition = payload.get("condition")
    if not isinstance(condition, str):
        return WorkerOutcome(
            index=index,
            party=party,
            condition=None,
            assigned_post_ids=None,
            latency_ms=None,
            hard_failure=True,
            error=f"missing/malformed condition in response: {payload!r}",
        )
    assigned_post_ids_raw = payload.get("assigned_post_ids")
    if not isinstance(assigned_post_ids_raw, list) or not all(
        isinstance(x, str) for x in assigned_post_ids_raw
    ):
        return WorkerOutcome(
            index=index,
            party=party,
            condition=condition,
            assigned_post_ids=None,
            latency_ms=None,
            hard_failure=True,
            error="missing/malformed assigned_post_ids in response",
        )
    return WorkerOutcome(
        index=index,
        party=party,
        condition=condition,
        assigned_post_ids=assigned_post_ids_raw,
        latency_ms=duration_ms,
        hard_failure=False,
        error=None,
    )


def _write_report_files(
    *,
    report_dir: Path,
    summary: dict[str, Any],
    outcomes: list[WorkerOutcome],
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    summary_path = report_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    outcomes_path = report_dir / "outcomes.csv"
    with outcomes_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "index",
                "party",
                "condition",
                "latency_ms",
                "hard_failure",
                "skipped",
                "error",
            ]
        )
        for outcome in sorted(outcomes, key=lambda o: o.index):
            writer.writerow(
                [
                    outcome.index,
                    outcome.party,
                    outcome.condition or "",
                    f"{outcome.latency_ms:.3f}" if outcome.latency_ms is not None else "",
                    str(outcome.hard_failure).lower(),
                    str(outcome.skipped).lower(),
                    outcome.error or "",
                ]
            )


def _query_items(table, *, study_id: str, sort_key: str, sort_prefix: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    last_key = None
    key_condition = Key("study_id").eq(study_id) & Key(sort_key).begins_with(sort_prefix)
    while True:
        query_kwargs: dict[str, Any] = {
            "KeyConditionExpression": key_condition,
            "ConsistentRead": True,
        }
        if last_key:
            query_kwargs["ExclusiveStartKey"] = last_key
        response = table.query(**query_kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
    return items


def _cleanup_after_run(
    *,
    cleanup_ctx: CleanupContext,
    study_id: str,
    study_iteration_id: str,
) -> dict[str, int]:
    dynamodb: Any = boto3.resource("dynamodb", region_name=cleanup_ctx.region_name)
    user_table = dynamodb.Table(cleanup_ctx.user_assignments_table_name)
    counter_table = dynamodb.Table(cleanup_ctx.assignment_counter_table_name)
    s3 = boto3.client("s3", region_name=cleanup_ctx.region_name)

    user_items = _query_items(
        user_table,
        study_id=study_id,
        sort_key="iteration_user_key",
        sort_prefix=f"{study_iteration_id}#",
    )
    counter_items = _query_items(
        counter_table,
        study_id=study_id,
        sort_key="iteration_assignment_key",
        sort_prefix=f"{study_iteration_id}#",
    )
    with user_table.batch_writer() as batch:
        for item in user_items:
            batch.delete_item(
                Key={"study_id": item["study_id"], "iteration_user_key": item["iteration_user_key"]}
            )
    with counter_table.batch_writer() as batch:
        for item in counter_items:
            batch.delete_item(
                Key={
                    "study_id": item["study_id"],
                    "iteration_assignment_key": item["iteration_assignment_key"],
                }
            )

    deleted_s3 = 0
    # Keep prefix isolated to load harness-owned fixture paths.
    prefix = f"{DEFAULT_S3_PREFIX}/~handler-load/{study_iteration_id}/"
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": cleanup_ctx.bucket_name, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        response = s3.list_objects_v2(**kwargs)
        contents = response.get("Contents", [])
        for obj in contents:
            s3.delete_object(Bucket=cleanup_ctx.bucket_name, Key=obj["Key"])
            deleted_s3 += 1
        if not response.get("IsTruncated"):
            break
        token = response.get("NextContinuationToken")

    return {
        "deleted_user_assignments": len(user_items),
        "deleted_assignment_counters": len(counter_items),
        "deleted_s3_objects": deleted_s3,
    }


def build_cleanup_context_from_env() -> CleanupContext:
    return CleanupContext(
        region_name=os.environ["AWS_REGION"],
        user_assignments_table_name=os.environ["USER_ASSIGNMENTS_TABLE_NAME"],
        assignment_counter_table_name=os.environ["STUDY_ASSIGNMENT_COUNTER_TABLE_NAME"],
    )


def run_handler_load(
    config: LoadRunnerConfig,
    *,
    cleanup_ctx: CleanupContext | None = None,
) -> LoadRunResult:
    if config.users <= 0:
        raise ValueError("users must be > 0")
    if config.max_workers <= 0:
        raise ValueError("max_workers must be > 0")
    study_iteration_id = config.study_iteration_id or make_study_iteration_id()
    iteration_slug = make_iteration_slug(study_iteration_id)
    parties = parties_for_run(n=config.users, scenario=config.scenario, seed=config.seed)
    ground_truth_post_pool = load_ground_truth_post_pool()

    stop_event = threading.Event()
    all_outcomes: list[WorkerOutcome] = []
    in_flight: set[Future[WorkerOutcome]] = set()
    future_to_index: dict[Future[WorkerOutcome], int] = {}
    next_index = 0
    submitted = 0
    t0 = time.perf_counter()

    with ThreadPoolExecutor(max_workers=min(32, config.max_workers)) as executor:
        while next_index < config.users or in_flight:
            while (
                next_index < config.users
                and len(in_flight) < min(32, config.max_workers)
                and not stop_event.is_set()
            ):
                future = executor.submit(
                    _worker_invoke,
                    index=next_index,
                    party=parties[next_index],
                    scheduled_offset_seconds=stagger_seconds(
                        index=next_index, n=config.users, ramp_seconds=config.ramp_seconds
                    ),
                    t0=t0,
                    stop_event=stop_event,
                    invoker=config.invoker,
                    study_id=config.study_id,
                    study_iteration_id=study_iteration_id,
                    iteration_slug=iteration_slug,
                )
                in_flight.add(future)
                future_to_index[future] = next_index
                next_index += 1
                submitted += 1

            if not in_flight:
                break
            done, pending = wait(in_flight, return_when=FIRST_COMPLETED)
            in_flight = set(pending)
            for future in done:
                outcome = future.result()
                all_outcomes.append(outcome)
                if outcome.hard_failure:
                    stop_event.set()
                future_to_index.pop(future, None)

    hard_failures = [o for o in all_outcomes if o.hard_failure]
    successes = [
        o for o in all_outcomes if not o.hard_failure and not o.skipped and o.latency_ms is not None
    ]
    skipped = [o for o in all_outcomes if o.skipped]
    success_latencies_ms = [o.latency_ms for o in successes if o.latency_ms is not None]
    latency_summary = summarize_ms(success_latencies_ms)
    request_condition_counts: Counter[tuple[str, str]] = Counter(
        (o.party, o.condition) for o in successes if o.condition is not None
    )
    distribution_result: DistributionCheckResult = assert_distribution(
        scenario=config.scenario,
        request_condition_counts=request_condition_counts,
    )

    invariant_errors: list[str] = []
    for outcome in successes:
        result: PostInvariantResult = validate_handler_assigned_post_ids(
            assigned_post_ids_raw=outcome.assigned_post_ids,
            ground_truth_post_pool=ground_truth_post_pool,
            context=f"user_index={outcome.index}",
        )
        if not result.valid and result.error:
            invariant_errors.append(result.error)
    invariant_error_examples = invariant_errors[:10]

    summary: dict[str, Any] = {
        "backend": config.backend,
        "study_id": config.study_id,
        "study_iteration_id": study_iteration_id,
        "scenario": config.scenario,
        "seed": config.seed,
        "users_requested": config.users,
        "users_submitted": submitted,
        "users_completed": len(all_outcomes),
        "users_succeeded": len(successes),
        "users_skipped_after_stop": len(skipped),
        "hard_failures": len(hard_failures),
        "hard_failure_examples": [o.error for o in hard_failures[:10] if o.error],
        "invariant_violations": len(invariant_errors),
        "invariant_violation_examples": invariant_error_examples,
        "max_workers": min(32, config.max_workers),
        "ramp_seconds": config.ramp_seconds,
        "latency_ms": latency_summary,
        "distribution": asdict(distribution_result),
    }

    if config.cleanup_after and cleanup_ctx is not None:
        summary["cleanup"] = _cleanup_after_run(
            cleanup_ctx=cleanup_ctx,
            study_id=config.study_id,
            study_iteration_id=study_iteration_id,
        )

    if config.report_dir is not None:
        _write_report_files(report_dir=config.report_dir, summary=summary, outcomes=all_outcomes)
        summary["report_dir"] = str(config.report_dir)

    passed = len(hard_failures) == 0 and len(invariant_errors) <= 10 and distribution_result.ok
    summary["passed"] = passed
    exit_code = 0 if passed else 1

    print(
        "Load run complete: "
        f"backend={config.backend} users={config.users} succeeded={len(successes)} "
        f"hard_failures={len(hard_failures)} invariant_violations={len(invariant_errors)} "
        f"distribution_ok={distribution_result.ok} exit_code={exit_code}"
    )
    return LoadRunResult(exit_code=exit_code, summary=summary)

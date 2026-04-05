"""CLI entrypoint for get_study_assignment load tests."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from lambdas.get_study_assignment.load_tests.handler_load_runner import (
    LoadRunnerConfig,
    build_cleanup_context_from_env,
    run_handler_load,
)
from lambdas.get_study_assignment.load_tests.study_ids import DEFAULT_STUDY_ID
from lambdas.get_study_assignment.smoke_tests.run_handler_smoke_tests import (
    SMOKE_BACKENDS,
    _parse_backend,
    _validate_prod_smoke_env,
    build_invoker,
)

DEFAULT_USERS = 2000
DEFAULT_RAMP_SECONDS = 120.0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=SMOKE_BACKENDS, default=None)
    parser.add_argument("--study-id", default=DEFAULT_STUDY_ID)
    parser.add_argument("--study-iteration-id", default=None)
    parser.add_argument("--users", type=int, default=DEFAULT_USERS)
    parser.add_argument("--ramp-seconds", type=float, default=DEFAULT_RAMP_SECONDS)
    parser.add_argument("--scenario", choices=("alternate", "random"), default="random")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-workers", type=int, default=32)
    parser.add_argument("--report-dir", type=Path, default=None)
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Keep iteration data in DynamoDB/S3 for inspection after a run.",
    )
    return parser


def _validate_prod_load_env() -> None:
    if os.getenv("LOAD_ALLOW_PROD") != "true":
        raise RuntimeError(
            "Prod load tests refused: set LOAD_ALLOW_PROD=true to acknowledge "
            "you intend to invoke the deployed Lambda and generate load."
        )
    _validate_prod_smoke_env()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    backend = _parse_backend(args.backend)
    if backend == "prod":
        _validate_prod_load_env()

    invoker = build_invoker(backend=backend)
    cleanup_enabled = not args.no_cleanup
    cleanup_ctx = build_cleanup_context_from_env() if cleanup_enabled else None

    config = LoadRunnerConfig(
        invoker=invoker,
        backend=backend,
        users=args.users,
        scenario=args.scenario,
        ramp_seconds=args.ramp_seconds,
        max_workers=args.max_workers,
        study_id=args.study_id,
        study_iteration_id=args.study_iteration_id,
        seed=args.seed,
        report_dir=args.report_dir,
        cleanup_after=cleanup_enabled,
    )
    result = run_handler_load(config, cleanup_ctx=cleanup_ctx)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

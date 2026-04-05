"""Unified smoke runner for get_study_assignment across backends."""

from __future__ import annotations

import argparse
import os

from lambdas.get_study_assignment.smoke_tests.handler_invokers import (
    DockerHandlerInvoker,
    HandlerInvoker,
    LocalHandlerInvoker,
    ProdLambdaHandlerInvoker,
)
from lambdas.get_study_assignment.smoke_tests.handler_smoke_suite import TestHandlerSmokeSuite
from lib.smoke_testing_utils import run_smoke_tests
from lib.testing_utils import _require_env

SMOKE_BACKENDS = ("local", "docker", "prod")
DEFAULT_DOCKER_INVOKE_URL = "http://127.0.0.1:9000/2015-03-31/functions/function/invocations"

_PROD_SMOKE_ENV_VARS = (
    "AWS_REGION",
    "SMOKE_PROD_LAMBDA_NAME",
    "USER_ASSIGNMENTS_TABLE_NAME",
    "STUDY_ASSIGNMENT_COUNTER_TABLE_NAME",
)


def _validate_prod_smoke_env() -> None:
    """Refuse or fail fast with an explicit list of required prod smoke variables."""
    if os.getenv("SMOKE_ALLOW_PROD") != "true":
        raise RuntimeError(
            "Prod smoke tests refused: set SMOKE_ALLOW_PROD=true to acknowledge you intend to "
            "invoke the deployed Lambda and run the suite (fixtures use DynamoDB and S3)."
        )
    missing = [name for name in _PROD_SMOKE_ENV_VARS if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Prod smoke tests missing required environment variables: "
            + ", ".join(missing)
            + ". Required: AWS_REGION, SMOKE_PROD_LAMBDA_NAME, "
            "USER_ASSIGNMENTS_TABLE_NAME, STUDY_ASSIGNMENT_COUNTER_TABLE_NAME "
            "(tables match local/docker; the handler is invoked via lambda:InvokeFunction)."
        )


def _parse_backend(backend: str | None) -> str:
    selected = backend or os.getenv("SMOKE_BACKEND", "local")
    if selected not in SMOKE_BACKENDS:
        allowed = ", ".join(SMOKE_BACKENDS)
        raise ValueError(f"Unsupported SMOKE_BACKEND={selected!r}; expected one of: {allowed}")
    return selected


def _build_local_invoker() -> LocalHandlerInvoker:
    return LocalHandlerInvoker(
        region_name=_require_env("AWS_REGION"),
        user_assignments_table_name=_require_env("USER_ASSIGNMENTS_TABLE_NAME"),
        study_assignment_counter_table_name=_require_env("STUDY_ASSIGNMENT_COUNTER_TABLE_NAME"),
    )


def _build_docker_invoker() -> DockerHandlerInvoker:
    invoke_url = os.getenv("SMOKE_DOCKER_INVOKE_URL", DEFAULT_DOCKER_INVOKE_URL)
    timeout_seconds = float(os.getenv("SMOKE_DOCKER_TIMEOUT_SECONDS", "10"))
    return DockerHandlerInvoker(invoke_url=invoke_url, timeout_seconds=timeout_seconds)


def _build_prod_invoker() -> ProdLambdaHandlerInvoker:
    return ProdLambdaHandlerInvoker(
        region_name=_require_env("AWS_REGION"),
        function_name=_require_env("SMOKE_PROD_LAMBDA_NAME"),
        qualifier=os.getenv("SMOKE_PROD_LAMBDA_QUALIFIER"),
    )


def build_invoker(*, backend: str) -> HandlerInvoker:
    if backend == "local":
        return _build_local_invoker()
    if backend == "docker":
        return _build_docker_invoker()
    if backend == "prod":
        return _build_prod_invoker()
    raise ValueError(f"Unexpected backend: {backend}")


def run_for_backend(backend: str | None = None) -> int:
    selected_backend = _parse_backend(backend)
    if selected_backend == "prod":
        _validate_prod_smoke_env()
    invoker = build_invoker(backend=selected_backend)

    class ConfiguredHandlerSmokeSuite(TestHandlerSmokeSuite):
        INVOKER = invoker

    print(f"Running get_study_assignment smoke tests via backend={selected_backend!r}")
    return run_smoke_tests([ConfiguredHandlerSmokeSuite])


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend",
        choices=SMOKE_BACKENDS,
        default=None,
        help="Override backend selection (otherwise SMOKE_BACKEND env var is used).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return run_for_backend(args.backend)


if __name__ == "__main__":
    raise SystemExit(main())

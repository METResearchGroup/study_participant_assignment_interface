---
name: unified smoke runner
overview: Refactor get_study_assignment smoke testing into one shared suite with pluggable invocation backends so the same tests can run locally in-process, against Docker Lambda RIE, and against deployed Lambda.
todos:
  - id: extract-shared-suite
    content: Create shared handler smoke suite with invoke_handler seam and migrate all existing tests/fixtures unchanged.
    status: pending
  - id: add-invoker-layer
    content: Implement local/docker/prod invokers behind one protocol and consistent error handling.
    status: pending
  - id: add-unified-runner
    content: Create single runner that selects backend via env and executes suite through run_smoke_tests.
    status: pending
  - id: compatibility-docs
    content: Keep local script compatibility and add usage docs for local, docker, and prod modes.
    status: pending
  - id: verify-all-backends
    content: Run manual verification flows for local/docker/prod and confirm parity of smoke assertions.
    status: pending
isProject: false
---

# Unified Handler Smoke Runner Plan

## Goal

Create a single smoke test runner for `get_study_assignment` that executes one canonical test suite across multiple invocation targets (`local`, `docker`, `prod`) without duplicating assertions or fixture logic.

## Current Baseline

- Existing full test coverage and fixture lifecycle are in `[/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lambdas/get_study_assignment/smoke_tests/local_handler_smoke_test.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lambdas/get_study_assignment/smoke_tests/local_handler_smoke_test.py)`.
- Test orchestration helper (`setup -> test_* -> teardown` with aggregated reporting) is in `[/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/smoke_testing_utils.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lib/smoke_testing_utils.py)`.

## Target Architecture

- Extract the existing test cases into a shared suite that calls `self.invoke_handler(event)` instead of directly calling `h.handler(...)`.
- Provide backend-specific invokers that implement a common interface:
  - `local`: direct Python call to Lambda handler.
  - `docker`: HTTP POST to Lambda RIE endpoint (`/2015-03-31/functions/function/invocations`).
  - `prod`: AWS Lambda `Invoke` API via boto3.
- Add one runner script that selects backend via env/CLI and executes the shared suite using existing `run_smoke_tests`.

```mermaid
flowchart TD
  runner[run_handler_smoke_tests.py] --> config[backend config]
  config --> factory[build_invoker]
  factory --> localInvoker[LocalInvoker]
  factory --> dockerInvoker[DockerInvoker]
  factory --> prodInvoker[ProdInvoker]
  runner --> sharedSuite[shared suite tests]
  sharedSuite --> invokeMethod[invoke_handler(event)]
  invokeMethod --> localInvoker
  invokeMethod --> dockerInvoker
  invokeMethod --> prodInvoker
```



## File-Level Implementation Plan

- Add `[/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lambdas/get_study_assignment/smoke_tests/handler_smoke_suite.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lambdas/get_study_assignment/smoke_tests/handler_smoke_suite.py)`
  - Move/retain all current fixture setup, seed helpers, cleanup helpers, and `test_*` methods.
  - Introduce `invoke_handler(event)` seam used by all tests.
  - Keep deterministic expectations and current assertions unchanged.
- Add `[/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lambdas/get_study_assignment/smoke_tests/handler_invokers.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lambdas/get_study_assignment/smoke_tests/handler_invokers.py)`
  - Define `HandlerInvoker` protocol/base.
  - Implement `LocalHandlerInvoker`, `DockerHandlerInvoker`, `ProdLambdaHandlerInvoker`.
  - Normalize error handling so failures are actionable and backend-agnostic.
- Add `[/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py)`
  - Parse backend selector (`SMOKE_BACKEND` default `local`).
  - Read required backend-specific env vars.
  - Build invoker and pass into suite class/factory.
  - Call `run_smoke_tests(...)` and exit with aggregated status code.
- Keep compatibility wrappers:
  - Update or slim `[/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lambdas/get_study_assignment/smoke_tests/local_handler_smoke_test.py](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lambdas/get_study_assignment/smoke_tests/local_handler_smoke_test.py)` to delegate to new runner with `local` backend for backward compatibility.
  - Add optional convenience wrapper for Docker mode (if desired) that only sets defaults and delegates to runner.
- Add usage notes in `[/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lambdas/README.md](/Users/mark/Documents/work/worktree_study_participant_assignment_interface/lambdas/README.md)` (or nearby smoke test docs)
  - Commands for `local`, `docker`, and `prod` runs.
  - Required env vars per backend.

## Backend Contracts

- Local invoker
  - Input: event dict.
  - Behavior: call `lambdas.get_study_assignment.handler.handler(event, None)`.
- Docker invoker
  - Input: event dict.
  - Behavior: POST JSON to configured local URL.
  - Validate HTTP code and JSON payload shape; surface Lambda runtime errors clearly.
- Prod invoker
  - Input: event dict.
  - Behavior: `boto3.client("lambda").invoke(...)` against configured function name (+ optional qualifier).
  - Parse payload stream, detect `FunctionError`, and raise clear assertion/runtime failures.

## Configuration Plan

- Common env vars retained from current suite:
  - `AWS_REGION`, `USER_ASSIGNMENTS_TABLE_NAME`, `STUDY_ASSIGNMENT_COUNTER_TABLE_NAME`.
- New env vars:
  - `SMOKE_BACKEND=local|docker|prod`.
  - `SMOKE_DOCKER_INVOKE_URL` and optional timeout for docker.
  - `SMOKE_PROD_LAMBDA_NAME` and optional qualifier for prod.
  - Optional safety gate: `SMOKE_ALLOW_PROD=true` to prevent accidental prod runs.

## Manual Verification

- Local backend:
  - Run unified runner with `SMOKE_BACKEND=local`.
  - Expect same pass/fail behavior as existing `local_handler_smoke_test.py`.
- Docker backend:
  - Start container from `Dockerfiles/lambda_get_study_assignment.Dockerfile`.
  - Run unified runner with `SMOKE_BACKEND=docker`.
  - Confirm identical test outcomes and deterministic assertions.
- Prod backend:
  - Run unified runner with `SMOKE_BACKEND=prod` and required function env vars.
  - Confirm payload contract and idempotency tests pass without cross-test contamination.

## Risks and Mitigations

- Risk: backend drift in response/error shape.
  - Mitigation: normalize invoker return/exception behavior and keep tests backend-agnostic.
- Risk: accidental production invocation.
  - Mitigation: explicit prod safety flag and strict env validation before execution.
- Risk: duplicate state leakage between tests.
  - Mitigation: preserve current unique `study_id` + `study_iteration_id` generation and teardown paths unchanged.

## Rollout Strategy

1. Introduce shared suite + local invoker first; keep old script path working.
2. Add docker invoker and validate against local container.
3. Add prod invoker with safety gate and docs.
4. Optionally deprecate old per-backend scripts once unified runner is stable.


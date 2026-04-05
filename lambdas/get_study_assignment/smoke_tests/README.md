# get_study_assignment smoke tests

End-to-end smoke tests for the Lambda handler. One shared suite (`handler_smoke_suite.py`) runs through `run_handler_smoke_tests.py`, which picks how the handler is invoked: in-process (`local`), Lambda Runtime Interface Emulator in Docker (`docker`), or (when enabled) deployed Lambda (`prod`).

Run commands from the **repository root** with `PYTHONPATH=.` so `lambdas` and `lib` import correctly.

## Shared environment

Required for **local** and **docker** backends (tests seed/query DynamoDB and S3):

- `AWS_REGION`
- `USER_ASSIGNMENTS_TABLE_NAME`
- `STUDY_ASSIGNMENT_COUNTER_TABLE_NAME`

Use the same AWS credentials you use for normal development (profile, env vars, or instance role).

Backend selection:

- Env: `SMOKE_BACKEND=local|docker|prod` (default `local`)
- CLI: `uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py --backend docker`

## Local backend (default)

Invokes `handler` in the same Python process (fixtures still use real AWS for DynamoDB/S3).

```bash
PYTHONPATH=. AWS_REGION=us-east-2 \
  USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
  STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
  uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py
```

Explicit:

```bash
SMOKE_BACKEND=local ...
```

## Docker backend

Build and run the Lambda image (see `Dockerfiles/lambda_get_study_assignment.Dockerfile`), map port **9000 → 8080**, and ensure the **container** can reach AWS (e.g. mount credentials if you use a profile):

```bash
docker build -f Dockerfiles/lambda_get_study_assignment.Dockerfile -t get-study-assignment:local .
docker run --rm -p 9000:8080 \
  -e AWS_PROFILE=your-profile -e AWS_REGION=us-east-2 \
  -v "$HOME/.aws:/root/.aws:ro" \
  get-study-assignment:local
```

Then:

```bash
PYTHONPATH=. AWS_REGION=us-east-2 \
  USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
  STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
  SMOKE_BACKEND=docker \
  SMOKE_DOCKER_INVOKE_URL=http://127.0.0.1:9000/2015-03-31/functions/function/invocations \
  uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py
```

Optional:

- `SMOKE_DOCKER_TIMEOUT_SECONDS` (default `10`)

## Prod backend

**Stub (default):** there is no deployed `get_study_assignment` Lambda wired for this suite yet. `SMOKE_BACKEND=prod` prints a short message and exits **0**; no tests run.

```bash
SMOKE_BACKEND=prod uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py
```

(`PYTHONPATH=.` is only needed if your environment does not already resolve the `lambdas` package.)

**Live (when a function exists):** real `lambda.invoke` with the same assertions as local/docker:

```bash
PYTHONPATH=. AWS_REGION=us-east-2 \
  USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
  STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
  SMOKE_BACKEND=prod \
  SMOKE_PROD_ENABLED=true \
  SMOKE_ALLOW_PROD=true \
  SMOKE_PROD_LAMBDA_NAME=<lambda-function-name> \
  uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py
```

Optional:

- `SMOKE_PROD_LAMBDA_QUALIFIER` (version or alias)

## Layout

- `run_handler_smoke_tests.py` — CLI and backend selection
- `handler_smoke_suite.py` — shared tests and fixture lifecycle
- `handler_invokers.py` — local in-process, Docker RIE HTTP, optional prod `lambda.invoke`

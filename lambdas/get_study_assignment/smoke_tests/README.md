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
- CLI (full example from repo root):

  `PYTHONPATH=. AWS_REGION=us-east-2 USER_ASSIGNMENTS_TABLE_NAME=user_assignments STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py --backend docker`

## Local backend (default)

Invokes `handler` in the same Python process (fixtures still use real AWS for DynamoDB/S3).

Default backend is `local`; you can omit `SMOKE_BACKEND` or set it explicitly.

```bash
PYTHONPATH=. AWS_REGION=us-east-2 \
  USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
  STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
  uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py
```

Same run with an explicit backend env var:

```bash
PYTHONPATH=. AWS_REGION=us-east-2 \
  USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
  STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
  SMOKE_BACKEND=local \
  uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py
```

Same run using the CLI flag instead of `SMOKE_BACKEND`:

```bash
PYTHONPATH=. AWS_REGION=us-east-2 \
  USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
  STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
  uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py --backend local
```

## Docker backend

Use two terminals from the repo root. Replace `YOUR_AWS_PROFILE` with your profile name (or remove `-e AWS_PROFILE=...` if the container should use other credential env vars).

### Terminal 1 — build image and start Lambda RIE

```bash
docker build -f Dockerfiles/lambda_get_study_assignment.Dockerfile -t get-study-assignment:local .

docker run --rm --name get-study-assignment-smoke -p 9000:8080 \
  -e AWS_PROFILE=YOUR_AWS_PROFILE \
  -e AWS_REGION=us-east-2 \
  -v "$HOME/.aws:/root/.aws:ro" \
  get-study-assignment:local
```

### Terminal 2 — run smoke tests against RIE

```bash
PYTHONPATH=. AWS_REGION=us-east-2 \
  USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
  STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
  SMOKE_BACKEND=docker \
  SMOKE_DOCKER_INVOKE_URL=http://127.0.0.1:9000/2015-03-31/functions/function/invocations \
  uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py
```

Docker backend via CLI flag:

```bash
PYTHONPATH=. AWS_REGION=us-east-2 \
  USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
  STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
  SMOKE_DOCKER_INVOKE_URL=http://127.0.0.1:9000/2015-03-31/functions/function/invocations \
  uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py --backend docker
```

Optional longer HTTP timeout (full command):

```bash
PYTHONPATH=. AWS_REGION=us-east-2 \
  USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
  STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
  SMOKE_BACKEND=docker \
  SMOKE_DOCKER_INVOKE_URL=http://127.0.0.1:9000/2015-03-31/functions/function/invocations \
  SMOKE_DOCKER_TIMEOUT_SECONDS=30 \
  uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py
```

## Prod backend

**Stub (default):** there is no deployed `get_study_assignment` Lambda wired for this suite yet. `SMOKE_BACKEND=prod` prints a short message and exits **0**; no tests run.

```bash
PYTHONPATH=. SMOKE_BACKEND=prod \
  uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py
```

Stub via CLI flag:

```bash
PYTHONPATH=. uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py --backend prod
```

**Live (when a function exists):** real `lambda.invoke` with the same assertions as local/docker. Replace `REPLACE_WITH_LAMBDA_FUNCTION_NAME` with the function name.

```bash
PYTHONPATH=. AWS_REGION=us-east-2 \
  USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
  STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
  SMOKE_BACKEND=prod \
  SMOKE_PROD_ENABLED=true \
  SMOKE_ALLOW_PROD=true \
  SMOKE_PROD_LAMBDA_NAME=REPLACE_WITH_LAMBDA_FUNCTION_NAME \
  uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py
```

Live with an optional qualifier (version or alias):

```bash
PYTHONPATH=. AWS_REGION=us-east-2 \
  USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
  STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
  SMOKE_BACKEND=prod \
  SMOKE_PROD_ENABLED=true \
  SMOKE_ALLOW_PROD=true \
  SMOKE_PROD_LAMBDA_NAME=REPLACE_WITH_LAMBDA_FUNCTION_NAME \
  SMOKE_PROD_LAMBDA_QUALIFIER=REPLACE_WITH_ALIAS_OR_VERSION \
  uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py
```

## Layout

- `run_handler_smoke_tests.py` — CLI and backend selection
- `handler_smoke_suite.py` — shared tests and fixture lifecycle
- `handler_invokers.py` — local in-process, Docker RIE HTTP, optional prod `lambda.invoke`

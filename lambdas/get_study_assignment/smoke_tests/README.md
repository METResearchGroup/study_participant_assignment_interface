# get_study_assignment smoke tests

End-to-end smoke tests for the Lambda handler. One shared suite (`handler_smoke_suite.py`) runs through `run_handler_smoke_tests.py`, which picks how the handler is invoked: in-process (`local`), Lambda Runtime Interface Emulator in Docker (`docker`), or deployed Lambda via `lambda:InvokeFunction` (`prod`, gated by `SMOKE_ALLOW_PROD=true`).

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

For **prod parity** with default x86_64 Lambda, build **linux/amd64** (on Apple Silicon this may use QEMU and be slower):

```bash
docker buildx build --platform linux/amd64 --load \
  -f Dockerfiles/lambda_get_study_assignment.Dockerfile \
  -t get-study-assignment:local \
  .
```

ECR pushes should use **`./scripts/build_and_push_lambda_image_to_ecr.sh`** so the image platform always matches the function.

```bash
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

**Active path:** `SMOKE_BACKEND=prod` runs the same suite as local/docker, invoking the deployed function with `boto3` `lambda.invoke`. You must set `SMOKE_ALLOW_PROD=true` (safety gate) and supply the same DynamoDB table names and region as local/docker so fixtures can seed and tear down data.

**IAM:** the principal running the smoke tests needs **`lambda:InvokeFunction`** on the target function (and the usual DynamoDB/S3 permissions the suite already uses). If invoke is denied, errors call out `AccessDeniedException` and this permission; if the function name or region is wrong, expect `ResourceNotFoundException`.

```bash
PYTHONPATH=. AWS_REGION=us-east-2 \
  USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
  STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
  SMOKE_BACKEND=prod \
  SMOKE_ALLOW_PROD=true \
  SMOKE_PROD_LAMBDA_NAME=get_study_assignment \
  uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py
```

Same run using the CLI flag:

```bash
PYTHONPATH=. AWS_REGION=us-east-2 \
  USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
  STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
  SMOKE_ALLOW_PROD=true \
  SMOKE_PROD_LAMBDA_NAME=get_study_assignment \
  uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py --backend prod
```

Optional qualifier (version or alias):

```bash
PYTHONPATH=. AWS_REGION=us-east-2 \
  USER_ASSIGNMENTS_TABLE_NAME=user_assignments \
  STUDY_ASSIGNMENT_COUNTER_TABLE_NAME=study_assignment_counter \
  SMOKE_BACKEND=prod \
  SMOKE_ALLOW_PROD=true \
  SMOKE_PROD_LAMBDA_NAME=get_study_assignment \
  SMOKE_PROD_LAMBDA_QUALIFIER=REPLACE_WITH_ALIAS_OR_VERSION \
  uv run python lambdas/get_study_assignment/smoke_tests/run_handler_smoke_tests.py
```

Without `SMOKE_ALLOW_PROD=true`, the runner exits immediately with an explicit refusal (no Lambda call).

## Layout

- `run_handler_smoke_tests.py` — CLI and backend selection
- `handler_smoke_suite.py` — shared tests and fixture lifecycle
- `handler_invokers.py` — local in-process, Docker RIE HTTP, prod `lambda.invoke`

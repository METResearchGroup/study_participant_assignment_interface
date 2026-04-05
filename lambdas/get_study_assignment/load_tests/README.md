# get_study_assignment load tests

Threaded load harness for `lambdas/get_study_assignment/handler.py`.

## Run

From repo root:

```bash
uv run python -m lambdas.get_study_assignment.load_tests.run_handler_load_tests \
  --backend local \
  --users 5 \
  --ramp-seconds 2 \
  --scenario random \
  --seed 42 \
  --report-dir /tmp/load-report
```

Equivalent script path:

```bash
uv run python lambdas/get_study_assignment/load_tests/run_handler_load_tests.py \
  --backend local --users 5 --ramp-seconds 2 --scenario random --seed 42
```

## Defaults

- `--users` defaults to `2000`
- `--ramp-seconds` defaults to `120`
- `--scenario` defaults to `random`
- cleanup runs by default; pass `--no-cleanup` to preserve iteration artifacts

## Backends and env vars

Backends reuse smoke-test invokers and most env vars:

- `local` / `docker`: same required DynamoDB table env vars as smoke
- `docker`: optional `SMOKE_DOCKER_INVOKE_URL`, `SMOKE_DOCKER_TIMEOUT_SECONDS`
- `prod`: same Lambda selector vars as smoke (`SMOKE_PROD_LAMBDA_NAME`, optional qualifier)

Prod guard is stricter for load runs:

- must set `LOAD_ALLOW_PROD=true`
- must also satisfy smoke prod guard requirements

## Reports

When `--report-dir` is provided, the harness writes:

- `summary.json`: aggregate metrics and pass/fail details (no per-request latency arrays)
- `outcomes.csv`: per-request status rows

## Final stress run (default users)

After small checks pass, run one operator-led stress slice with default users:

```bash
uv run python -m lambdas.get_study_assignment.load_tests.run_handler_load_tests \
  --backend local \
  --ramp-seconds 120 \
  --scenario random \
  --seed 42 \
  --report-dir /tmp/load-report-2000
```

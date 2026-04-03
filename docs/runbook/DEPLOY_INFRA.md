# Deploy Infra Runbook

## Purpose

This runbook explains how to deploy the PR 3 DynamoDB infrastructure with Terraform in `us-east-2`, how to make sure the AWS CLI is working before deployment, and what to verify afterward in the AWS console.

## Prerequisites

- Terraform installed and available on your `PATH`
- Python 3.12 and `uv` installed
- AWS CLI v2 installed
- AWS credentials for the target AWS account with permission to:
  - create and update DynamoDB tables
  - read DynamoDB table metadata
  - read and write DynamoDB items

## AWS CLI Setup

### 1. Confirm the AWS CLI is installed

```bash
aws --version
```

Expected output:

```text
aws-cli/2.x.x ...
```

If `aws` is not found, install AWS CLI v2 and rerun `aws --version`.

### 2. Configure credentials

Use one of these supported approaches.

Option A: default profile

```bash
aws configure
```

Use these values when prompted:

- AWS Access Key ID: `<your access key>`
- AWS Secret Access Key: `<your secret key>`
- Default region name: `us-east-2`
- Default output format: `json`

Option B: named profile

```bash
aws configure --profile study-assignment
```

Then export the profile before any Terraform or smoke-test commands:

```bash
export AWS_PROFILE=study-assignment
export AWS_REGION=us-east-2
```

### 3. Verify the CLI can reach AWS

```bash
aws sts get-caller-identity
```

Expected output:

```json
{
  "UserId": "...",
  "Account": "...",
  "Arn": "..."
}
```

If this command fails, do not continue. Fix the credentials or profile setup first.

### 4. Verify the target region

```bash
aws configure get region
```

Expected output:

```text
us-east-2
```

If you are using a named profile, verify with:

```bash
aws configure get region --profile "$AWS_PROFILE"
```

## Python Environment Setup

From the repository root:

```bash
uv sync --all-groups
```

Expected output:

```text
Resolved ...
Installed ...
```

## Terraform Deploy

Run all commands from the repository root.

### 1. Set the region explicitly

```bash
export AWS_REGION=us-east-2
```

If using a named profile, also export:

```bash
export AWS_PROFILE=study-assignment
```

### 2. Initialize Terraform

```bash
terraform -chdir=infra init
```

Expected output:

```text
Terraform has been successfully initialized!
```

### 3. Validate the configuration

```bash
terraform -chdir=infra validate
```

Expected output:

```text
Success! The configuration is valid.
```

### 4. Review the plan

```bash
terraform -chdir=infra plan
```

Look for:

- creation of exactly two DynamoDB tables
- one table for `user_assignments`
- one table for `study_assignment_counter`
- region `us-east-2`

### 5. Apply the plan

```bash
terraform -chdir=infra apply
```

Type `yes` when prompted.

Expected output:

```text
Apply complete! Resources: ...
```

### 6. Capture the Terraform outputs

```bash
terraform -chdir=infra output
```

Look for the deployed table names. You will use these values for the smoke test.

If specific outputs are defined for the table names, capture them directly:

```bash
terraform -chdir=infra output user_assignments_table_name
terraform -chdir=infra output study_assignment_counter_table_name
```

## Smoke Test

Run the end-to-end DynamoDB smoke test after Terraform finishes successfully.

```bash
AWS_REGION=us-east-2 \
USER_ASSIGNMENTS_TABLE_NAME="$(terraform -chdir=infra output -raw user_assignments_table_name)" \
STUDY_ASSIGNMENT_COUNTER_TABLE_NAME="$(terraform -chdir=infra output -raw study_assignment_counter_table_name)" \
uv run python infra/tests/dynamodb_e2e_tests.py
```

Expected behavior:

- the script writes and reads a `user_assignments` record
- the script increments a missing `study_assignment_counter` row and gets `1`
- the script performs concurrent increments for one key and gets distinct sequential values
- the script prints a clear success message at the end

If the smoke test fails, do not trust the deployment. Inspect the table definitions and item data in the console before retrying.

## AWS Console Checks

Open the AWS console and switch to region `us-east-2`.

Go to DynamoDB, then verify the following.

### Table 1: `user_assignments`

Check:

- the table exists
- the table name matches the Terraform output
- the partition and sort keys match the intended PR 3 schema
- the smoke-test item exists

Open the table and inspect the inserted item. Confirm:

- `study_id` is present
- `study_iteration_id` is present
- `user_id` is present
- `payload` is stored as a JSON string
- inside `payload`, `metadata` is itself a JSON-dumped string
- `created_at` is present

### Table 2: `study_assignment_counter`

Check:

- the table exists
- the table name matches the Terraform output
- the partition and sort keys match the intended PR 3 schema
- the smoke-test counter row exists

Open the table and inspect the inserted item. Confirm:

- `study_id` is present
- `study_iteration_id` is present
- `study_unique_assignment_key` is present
- `counter` is present and reflects the smoke-test increments
- `created_at` is present
- `last_updated_at` is present

For the concurrent increment test, confirm the final stored `counter` value matches the number of successful increments performed by the script.

## Useful Troubleshooting Commands

Check caller identity again:

```bash
aws sts get-caller-identity
```

List DynamoDB tables in `us-east-2`:

```bash
aws dynamodb list-tables --region us-east-2
```

Describe a deployed table:

```bash
aws dynamodb describe-table \
  --region us-east-2 \
  --table-name "$(terraform -chdir=infra output -raw user_assignments_table_name)"
```

Show Terraform outputs:

```bash
terraform -chdir=infra output
```

## Done When

- AWS CLI works with `aws sts get-caller-identity`
- Terraform `init`, `validate`, `plan`, and `apply` succeed
- the smoke test succeeds in `us-east-2`
- both DynamoDB tables are visible in the AWS console
- the expected smoke-test items and counter values are visible in the AWS console

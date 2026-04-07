#!/usr/bin/env bash
# Build and push the get_study_assignment container to ECR, update the deployed Lambda to
# that image by digest, then run terraform apply so state records the same image URI.
#
# AWS region is fixed to us-east-2 (this stack).
#
# Run from the repository root. Requires: Docker, AWS CLI, terraform (infra initialized),
# and credentials with ECR push, lambda:UpdateFunctionCode, and terraform apply permissions.
#
#   ./scripts/deploy_get_study_assignment_lambda_image.sh
#
# Extra arguments are forwarded to scripts/build_and_push_lambda_image_to_ecr.sh, e.g.:
#
#   ./scripts/deploy_get_study_assignment_lambda_image.sh --platform linux/arm64
#
# Optional env:
#   TERRAFORM_CHDIR — Terraform config directory (default: infra)
#   DOCKER_PLATFORM   — passed implicitly via build script env if set

set -euo pipefail

# Read-only + exported in one shot (readonly then `export VAR=...` fails: export assigns).
declare -rx AWS_REGION="us-east-2"

usage() {
  echo "Usage: $0 [args to build_and_push_lambda_image_to_ecr.sh ...]" >&2
  echo "Runs in AWS region ${AWS_REGION} (hard-coded)." >&2
  echo "See scripts/build_and_push_lambda_image_to_ecr.sh for optional flags." >&2
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$ROOT" ]]; then
  echo "Could not find git repository root; run from inside the repo." >&2
  exit 1
fi
cd "$ROOT"

TF_DIR="${TERRAFORM_CHDIR:-infra}"
if [[ ! -d "$TF_DIR" ]]; then
  echo "Terraform directory not found: $TF_DIR (set TERRAFORM_CHDIR if needed)." >&2
  exit 1
fi

ECR_URL="$(terraform -chdir="$TF_DIR" output -raw ecr_repository_url)"
ECR_NAME="$(terraform -chdir="$TF_DIR" output -raw ecr_repository_name)"
LAMBDA_NAME="$(terraform -chdir="$TF_DIR" output -raw lambda_function_name)"

export ECR_REPOSITORY_URL="$ECR_URL"

echo "Using AWS region: ${AWS_REGION}"
echo "Using ECR repository: $ECR_NAME"
echo "Using Lambda function: $LAMBDA_NAME"
echo "Running build and push ..."
bash scripts/build_and_push_lambda_image_to_ecr.sh "$@"

DIGEST="$(
  aws ecr describe-images \
    --repository-name "$ECR_NAME" \
    --region "$AWS_REGION" \
    --image-ids imageTag=latest \
    --query 'imageDetails[0].imageDigest' \
    --output text
)"

if [[ -z "$DIGEST" || "$DIGEST" == "None" ]]; then
  echo "Failed to resolve ECR image digest for imageTag=latest." >&2
  exit 1
fi

IMAGE_URI="${ECR_URL}@${DIGEST}"
echo "Updating Lambda ${LAMBDA_NAME} to ${IMAGE_URI} ..."
aws lambda update-function-code \
  --function-name "$LAMBDA_NAME" \
  --region "$AWS_REGION" \
  --image-uri "$IMAGE_URI"

aws lambda wait function-updated-v2 \
  --function-name "$LAMBDA_NAME" \
  --region "$AWS_REGION"

echo "Syncing Terraform state (lambda_image_uri=digest) ..."
terraform -chdir="$TF_DIR" apply -auto-approve -input=false \
  -var="lambda_image_uri=${IMAGE_URI}"

echo "Done. Lambda ${LAMBDA_NAME} and Terraform state use ${IMAGE_URI}."

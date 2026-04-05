#!/usr/bin/env bash
# Build Dockerfiles/lambda_get_study_assignment.Dockerfile and push :latest plus an
# immutable tag to ECR. Run from repository root.
#
# Uses docker buildx with --load (single platform). Default platform is linux/amd64,
# matching AWS Lambda's default x86_64 architecture. On Apple Silicon, plain docker build
# would produce linux/arm64 and break an x86_64 function (Runtime.InvalidEntrypoint).
# Override with DOCKER_PLATFORM=linux/arm64 or --platform when the function is arm64/Graviton.
#
# Copy-paste (after ECR exists and terraform apply has been run at least once for outputs):
#
#   ECR_REPOSITORY_URL="$(terraform -chdir=infra output -raw ecr_repository_url)" AWS_REGION=us-east-2 ./scripts/build_and_push_lambda_image_to_ecr.sh
#
# Optional:
#   --repo-url <url>      overrides ECR_REPOSITORY_URL
#   --region <region>     overrides AWS_REGION
#   --platform <os/arch>  overrides DOCKER_PLATFORM (default from env or linux/amd64)
#
# Optional env:
#   DOCKER_PLATFORM — e.g. linux/arm64 for Graviton Lambda (default: linux/amd64)
#
# Required when not using flags:
#   ECR_REPOSITORY_URL — full repository URL without tag
#   AWS_REGION — e.g. us-east-2 (also used by aws ecr get-login-password)

set -euo pipefail

usage() {
  echo "Usage: ECR_REPOSITORY_URL=<url> AWS_REGION=<region> $0" >&2
  echo "   or: $0 --repo-url <url> --region <region> [--platform <os/arch>]" >&2
}

REPO_URL="${ECR_REPOSITORY_URL:-}"
REGION="${AWS_REGION:-}"
PLATFORM_CLI=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-url)
      REPO_URL="${2:?}"
      shift 2
      ;;
    --region)
      REGION="${2:?}"
      shift 2
      ;;
    --platform)
      PLATFORM_CLI="${2:?}"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

DOCKER_PLATFORM="${PLATFORM_CLI:-${DOCKER_PLATFORM:-linux/amd64}}"

if [[ -z "$REPO_URL" || -z "$REGION" ]]; then
  echo "ECR_REPOSITORY_URL and AWS_REGION are required." >&2
  usage
  exit 1
fi

REGISTRY_HOST="${REPO_URL%%/*}"
LOCAL_TAG="get_study_assignment:local"
if GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null)"; then
  IMMUTABLE_TAG="$GIT_SHA"
else
  IMMUTABLE_TAG="$(date -u +%Y%m%d%H%M%S)"
fi

echo "Building local image $LOCAL_TAG (platform ${DOCKER_PLATFORM}) ..."
docker buildx create --use 2>/dev/null || true
docker buildx build --platform "$DOCKER_PLATFORM" --load \
  -f Dockerfiles/lambda_get_study_assignment.Dockerfile \
  -t "$LOCAL_TAG" \
  .

echo "Tagging ${REPO_URL}:latest and ${REPO_URL}:${IMMUTABLE_TAG} ..."
docker tag "$LOCAL_TAG" "${REPO_URL}:latest"
docker tag "$LOCAL_TAG" "${REPO_URL}:${IMMUTABLE_TAG}"

echo "Logging in to $REGISTRY_HOST ..."
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY_HOST"

echo "Pushing ..."
docker push "${REPO_URL}:latest"
docker push "${REPO_URL}:${IMMUTABLE_TAG}"

echo "Pushed ${REPO_URL}:latest"
echo "Pushed ${REPO_URL}:${IMMUTABLE_TAG}"

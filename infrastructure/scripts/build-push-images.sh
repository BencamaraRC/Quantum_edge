#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TF_DIR="$SCRIPT_DIR/../terraform"

echo "==> Reading Terraform outputs..."
AWS_REGION=$(terraform -chdir="$TF_DIR" output -raw aws_region)
AWS_ACCOUNT_ID=$(terraform -chdir="$TF_DIR" output -raw aws_account_id)
ECR_AGENT_URL=$(terraform -chdir="$TF_DIR" output -raw ecr_agent_url)
ECR_COORDINATOR_URL=$(terraform -chdir="$TF_DIR" output -raw ecr_coordinator_url)
ECR_DASHBOARD_URL=$(terraform -chdir="$TF_DIR" output -raw ecr_dashboard_url)

echo "==> Logging in to ECR..."
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

IMAGE_TAG="${IMAGE_TAG:-latest}"

echo "==> Building agent image..."
docker build \
  -t "$ECR_AGENT_URL:$IMAGE_TAG" \
  -f "$PROJECT_ROOT/infrastructure/docker/Dockerfile.agent" \
  "$PROJECT_ROOT"

echo "==> Building coordinator image..."
docker build \
  -t "$ECR_COORDINATOR_URL:$IMAGE_TAG" \
  -f "$PROJECT_ROOT/infrastructure/docker/Dockerfile.coordinator" \
  "$PROJECT_ROOT"

echo "==> Building dashboard image..."
docker build \
  -t "$ECR_DASHBOARD_URL:$IMAGE_TAG" \
  -f "$PROJECT_ROOT/infrastructure/docker/Dockerfile.dashboard" \
  "$PROJECT_ROOT"

echo "==> Pushing agent image..."
docker push "$ECR_AGENT_URL:$IMAGE_TAG"

echo "==> Pushing coordinator image..."
docker push "$ECR_COORDINATOR_URL:$IMAGE_TAG"

echo "==> Pushing dashboard image..."
docker push "$ECR_DASHBOARD_URL:$IMAGE_TAG"

echo "==> All images built and pushed successfully."
echo "    Agent:       $ECR_AGENT_URL:$IMAGE_TAG"
echo "    Coordinator: $ECR_COORDINATOR_URL:$IMAGE_TAG"
echo "    Dashboard:   $ECR_DASHBOARD_URL:$IMAGE_TAG"

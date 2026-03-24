#!/usr/bin/env bash
set -euo pipefail

# ─── Configuration ───
AWS_ACCOUNT_ID="661659055535"
AWS_REGION="us-east-1"
ECR_BASE="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
ECS_CLUSTER="qe-production"
DASHBOARD_REPO="quantum-edge/dashboard"
API_REPO="quantum-edge/agent"
TAG="${1:-latest}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "╔══════════════════════════════════════════╗"
echo "║   Quantum Edge — ECS Fargate Deploy      ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Account:  ${AWS_ACCOUNT_ID}"
echo "Region:   ${AWS_REGION}"
echo "Tag:      ${TAG}"
echo "Root:     ${PROJECT_ROOT}"
echo ""

# ─── Step 1: ECR Login ───
echo "→ Logging in to ECR..."
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_BASE}"
echo ""

# ─── Step 2: Build Dashboard Image ───
echo "→ Building dashboard image..."
docker build \
  -f "${PROJECT_ROOT}/infrastructure/docker/Dockerfile.dashboard" \
  --build-arg VITE_API_URL="" \
  -t "${ECR_BASE}/${DASHBOARD_REPO}:${TAG}" \
  "${PROJECT_ROOT}"
echo ""

# ─── Step 3: Build API Image ───
echo "→ Building API image..."
docker build \
  -f "${PROJECT_ROOT}/infrastructure/docker/Dockerfile.agent" \
  -t "${ECR_BASE}/${API_REPO}:${TAG}" \
  "${PROJECT_ROOT}"
echo ""

# ─── Step 4: Push Images ───
echo "→ Pushing dashboard image..."
docker push "${ECR_BASE}/${DASHBOARD_REPO}:${TAG}"
echo ""

echo "→ Pushing API image..."
docker push "${ECR_BASE}/${API_REPO}:${TAG}"
echo ""

# ─── Step 5: Force New Deployment ───
echo "→ Redeploying ECS services..."
aws ecs update-service \
  --cluster "${ECS_CLUSTER}" \
  --service "qe-production-dashboard" \
  --force-new-deployment \
  --region "${AWS_REGION}" \
  --no-cli-pager

aws ecs update-service \
  --cluster "${ECS_CLUSTER}" \
  --service "qe-production-api" \
  --force-new-deployment \
  --region "${AWS_REGION}" \
  --no-cli-pager

echo ""
echo "✓ Deploy complete! Services are restarting."
echo "  Monitor: aws ecs describe-services --cluster ${ECS_CLUSTER} --services qe-production-dashboard qe-production-api --region ${AWS_REGION} --query 'services[].{name:serviceName,running:runningCount,desired:desiredCount,status:status}'"

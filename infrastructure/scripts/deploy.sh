#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$INFRA_DIR/terraform"
K8S_DIR="$INFRA_DIR/k8s"

echo "==> Reading Terraform outputs..."
export AWS_REGION=$(terraform -chdir="$TF_DIR" output -raw aws_region)
export CLUSTER_NAME=$(terraform -chdir="$TF_DIR" output -raw cluster_name)
export ECR_AGENT_URL=$(terraform -chdir="$TF_DIR" output -raw ecr_agent_url)
export ECR_COORDINATOR_URL=$(terraform -chdir="$TF_DIR" output -raw ecr_coordinator_url)
export ECR_DASHBOARD_URL=$(terraform -chdir="$TF_DIR" output -raw ecr_dashboard_url)
export REDIS_ENDPOINT=$(terraform -chdir="$TF_DIR" output -raw redis_endpoint)
export DB_ENDPOINT=$(terraform -chdir="$TF_DIR" output -raw db_endpoint)
export DB_NAME=$(terraform -chdir="$TF_DIR" output -raw db_name)

# Parse DB host and port from endpoint (host:port format)
export DB_HOST="${DB_ENDPOINT%%:*}"
export DB_PORT="${DB_ENDPOINT##*:}"
export DB_USERNAME="${DB_USERNAME:-qe_user}"

# Secrets must be set in the environment
: "${DB_PASSWORD:?DB_PASSWORD must be set}"
: "${ALPACA_API_KEY:?ALPACA_API_KEY must be set}"
: "${ALPACA_SECRET_KEY:?ALPACA_SECRET_KEY must be set}"
export FINNHUB_API_KEY="${FINNHUB_API_KEY:-}"
export NEWSAPI_KEY="${NEWSAPI_KEY:-}"
export UNUSUAL_WHALES_API_KEY="${UNUSUAL_WHALES_API_KEY:-}"

echo "==> Configuring kubectl for cluster: $CLUSTER_NAME"
aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER_NAME"

echo "==> Applying namespace..."
kubectl apply -f "$K8S_DIR/namespace.yaml"

echo "==> Applying ConfigMap..."
envsubst < "$K8S_DIR/configmap.yaml" | kubectl apply -f -

echo "==> Applying Secrets..."
envsubst < "$K8S_DIR/secrets.yaml" | kubectl apply -f -

echo "==> Running init jobs..."
# Delete old jobs if they exist (idempotent re-deploy)
kubectl delete job init-timescaledb -n quantum-edge --ignore-not-found
kubectl delete job init-redis-streams -n quantum-edge --ignore-not-found

envsubst < "$K8S_DIR/jobs/init-timescaledb.yaml" | kubectl apply -f -
envsubst < "$K8S_DIR/jobs/init-redis-streams.yaml" | kubectl apply -f -

echo "==> Waiting for init jobs to complete..."
kubectl wait --for=condition=complete --timeout=120s job/init-timescaledb -n quantum-edge || true
kubectl wait --for=condition=complete --timeout=120s job/init-redis-streams -n quantum-edge || true

echo "==> Deploying agents..."
for f in "$K8S_DIR"/agents/*.yaml; do
  envsubst < "$f" | kubectl apply -f -
done

echo "==> Deploying coordinator..."
envsubst < "$K8S_DIR/coordinator/deployment.yaml" | kubectl apply -f -

echo "==> Deploying API..."
envsubst < "$K8S_DIR/api/deployment.yaml" | kubectl apply -f -
kubectl apply -f "$K8S_DIR/api/service.yaml"

echo "==> Deploying dashboard..."
envsubst < "$K8S_DIR/dashboard/deployment.yaml" | kubectl apply -f -
kubectl apply -f "$K8S_DIR/dashboard/service.yaml"

echo "==> Applying ingress..."
kubectl apply -f "$K8S_DIR/ingress.yaml"

echo "==> Waiting for rollouts..."
kubectl rollout status deployment/qe-api -n quantum-edge --timeout=180s
kubectl rollout status deployment/qe-dashboard -n quantum-edge --timeout=180s
kubectl rollout status deployment/coordinator -n quantum-edge --timeout=180s

for i in 01 02 03 04 05 06 07; do
  name=$(ls "$K8S_DIR/agents/" | grep "agent-${i}" | sed 's/.yaml//')
  kubectl rollout status deployment/"$name" -n quantum-edge --timeout=180s
done

echo ""
echo "==> Deployment complete!"
echo ""
echo "==> Fetching ALB hostname..."
ALB=$(kubectl get ingress qe-ingress -n quantum-edge -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "pending")
echo "    ALB: http://$ALB"
echo "    API: http://$ALB/api/health"
echo "    Dashboard: http://$ALB/"
echo ""
echo "==> Pod status:"
kubectl get pods -n quantum-edge

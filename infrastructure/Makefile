.PHONY: init plan apply build deploy status destroy

TF_DIR := terraform
SCRIPTS_DIR := scripts

# ─── Terraform ───

init:
	terraform -chdir=$(TF_DIR) init

plan:
	terraform -chdir=$(TF_DIR) plan

apply:
	terraform -chdir=$(TF_DIR) apply

destroy:
	terraform -chdir=$(TF_DIR) destroy

# ─── Docker ───

build:
	bash $(SCRIPTS_DIR)/build-push-images.sh

# ─── Kubernetes ───

deploy:
	bash $(SCRIPTS_DIR)/deploy.sh

status:
	@echo "==> Pods"
	@kubectl get pods -n quantum-edge
	@echo ""
	@echo "==> Services"
	@kubectl get svc -n quantum-edge
	@echo ""
	@echo "==> Ingress"
	@kubectl get ingress -n quantum-edge
	@echo ""
	@echo "==> Jobs"
	@kubectl get jobs -n quantum-edge

logs:
	@echo "Usage: make logs POD=<pod-name>"
	@echo "Example: make logs POD=agent-01-news-scanner"
	kubectl logs -f deployment/$(POD) -n quantum-edge

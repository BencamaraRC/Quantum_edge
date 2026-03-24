output "cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS cluster API endpoint"
  value       = module.eks.cluster_endpoint
}

output "cluster_certificate_authority" {
  description = "EKS cluster CA certificate (base64)"
  value       = module.eks.cluster_certificate_authority
  sensitive   = true
}

output "ecr_agent_url" {
  description = "ECR repository URL for agent image"
  value       = module.ecr.agent_repository_url
}

output "ecr_coordinator_url" {
  description = "ECR repository URL for coordinator image"
  value       = module.ecr.coordinator_repository_url
}

output "ecr_dashboard_url" {
  description = "ECR repository URL for dashboard image"
  value       = module.ecr.dashboard_repository_url
}

output "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint"
  value       = module.elasticache.redis_endpoint
}

output "db_endpoint" {
  description = "RDS PostgreSQL endpoint"
  value       = module.rds.db_endpoint
}

output "db_name" {
  description = "RDS database name"
  value       = module.rds.db_name
}

output "aws_region" {
  description = "AWS region"
  value       = var.aws_region
}

output "aws_account_id" {
  description = "AWS account ID"
  value       = data.aws_caller_identity.current.account_id
}

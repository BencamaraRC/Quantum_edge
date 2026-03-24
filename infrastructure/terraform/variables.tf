variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

variable "eks_cluster_version" {
  description = "Kubernetes version for EKS"
  type        = string
  default     = "1.29"
}

variable "eks_node_instance_type" {
  description = "EC2 instance type for EKS managed node group"
  type        = string
  default     = "t3.large"
}

variable "eks_node_desired_size" {
  description = "Desired number of worker nodes"
  type        = number
  default     = 3
}

variable "eks_node_min_size" {
  description = "Minimum number of worker nodes"
  type        = number
  default     = 2
}

variable "eks_node_max_size" {
  description = "Maximum number of worker nodes"
  type        = number
  default     = 5
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.r6g.large"
}

variable "db_allocated_storage" {
  description = "RDS allocated storage in GB"
  type        = number
  default     = 100
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "quantum_edge"
}

variable "db_username" {
  description = "Database master username"
  type        = string
  default     = "qe_user"
}

variable "redis_node_type" {
  description = "ElastiCache node type"
  type        = string
  default     = "cache.r7g.large"
}

variable "redis_num_cache_clusters" {
  description = "Number of Redis cache clusters (nodes)"
  type        = number
  default     = 2
}

# ─── ECS / API Secrets ───

variable "database_url" {
  description = "PostgreSQL connection string for API"
  type        = string
  sensitive   = true
  default     = ""
}

variable "redis_url" {
  description = "Redis connection string for API"
  type        = string
  sensitive   = true
  default     = ""
}

variable "alpaca_api_key" {
  description = "Alpaca API key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "alpaca_api_secret" {
  description = "Alpaca API secret"
  type        = string
  sensitive   = true
  default     = ""
}

variable "alpaca_base_url" {
  description = "Alpaca base URL"
  type        = string
  default     = "https://paper-api.alpaca.markets"
}

variable "qe_auth_secret" {
  description = "JWT auth secret for QE API"
  type        = string
  sensitive   = true
  default     = ""
}

variable "qe_admin_username" {
  description = "Admin username for QE dashboard"
  type        = string
  default     = "admin"
}

variable "qe_admin_password" {
  description = "Admin password for QE dashboard"
  type        = string
  sensitive   = true
  default     = ""
}

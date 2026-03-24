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

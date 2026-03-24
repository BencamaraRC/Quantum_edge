variable "environment" {
  description = "Environment name"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "public_subnets" {
  description = "Public subnet IDs for ALB"
  type        = list(string)
}

variable "private_subnets" {
  description = "Private subnet IDs for ECS tasks"
  type        = list(string)
}

variable "dashboard_image" {
  description = "ECR image URI for dashboard"
  type        = string
}

variable "api_image" {
  description = "ECR image URI for API"
  type        = string
}

# ─── API Environment Variables ───

variable "database_url" {
  description = "PostgreSQL connection string"
  type        = string
  sensitive   = true
}

variable "redis_url" {
  description = "Redis connection string"
  type        = string
  sensitive   = true
}

variable "alpaca_api_key" {
  description = "Alpaca API key"
  type        = string
  sensitive   = true
}

variable "alpaca_api_secret" {
  description = "Alpaca API secret"
  type        = string
  sensitive   = true
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
}

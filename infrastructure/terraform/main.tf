data "aws_caller_identity" "current" {}

provider "aws" {
  region = var.aws_region
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name]
  }
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name]
    }
  }
}

# ─── VPC ───

module "vpc" {
  source = "./modules/vpc"

  environment = var.environment
  aws_region  = var.aws_region
  vpc_cidr    = var.vpc_cidr
}

# ─── EKS ───

module "eks" {
  source = "./modules/eks"

  environment        = var.environment
  aws_region         = var.aws_region
  vpc_id             = module.vpc.vpc_id
  private_subnets    = module.vpc.private_subnets
  cluster_version    = var.eks_cluster_version
  node_instance_type = var.eks_node_instance_type
  node_desired_size  = var.eks_node_desired_size
  node_min_size      = var.eks_node_min_size
  node_max_size      = var.eks_node_max_size
}

# ─── RDS (TimescaleDB) ───

module "rds" {
  source = "./modules/rds"

  environment       = var.environment
  vpc_id            = module.vpc.vpc_id
  vpc_cidr          = module.vpc.vpc_cidr_block
  subnet_ids        = module.vpc.private_subnets
  instance_class    = var.db_instance_class
  allocated_storage = var.db_allocated_storage
  db_name           = var.db_name
  db_username       = var.db_username
}

# ─── ElastiCache (Redis) ───

module "elasticache" {
  source = "./modules/elasticache"

  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  vpc_cidr           = module.vpc.vpc_cidr_block
  subnet_ids         = module.vpc.private_subnets
  node_type          = var.redis_node_type
  num_cache_clusters = var.redis_num_cache_clusters
}

# ─── ECR ───

module "ecr" {
  source = "./modules/ecr"

  environment = var.environment
}

# ─── ECS Fargate (Dashboard + API) ───

module "ecs" {
  source = "./modules/ecs"

  environment     = var.environment
  aws_region      = var.aws_region
  vpc_id          = module.vpc.vpc_id
  public_subnets  = module.vpc.public_subnets
  private_subnets = module.vpc.private_subnets

  dashboard_image = "${module.ecr.dashboard_repository_url}:latest"
  api_image       = "${module.ecr.agent_repository_url}:latest"

  database_url      = var.database_url
  redis_url         = var.redis_url
  alpaca_api_key    = var.alpaca_api_key
  alpaca_api_secret = var.alpaca_api_secret
  alpaca_base_url   = var.alpaca_base_url
  qe_auth_secret    = var.qe_auth_secret
  qe_admin_username = var.qe_admin_username
  qe_admin_password = var.qe_admin_password
}

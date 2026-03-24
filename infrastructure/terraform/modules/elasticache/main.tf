resource "aws_elasticache_subnet_group" "this" {
  name       = "qe-redis-${var.environment}"
  subnet_ids = var.subnet_ids

  tags = {
    Environment = var.environment
    Project     = "quantum-edge"
  }
}

resource "aws_security_group" "redis" {
  name_prefix = "qe-redis-${var.environment}-"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    cidr_blocks     = [var.vpc_cidr]
    description     = "Redis from VPC"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Environment = var.environment
    Project     = "quantum-edge"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "qe-redis-${var.environment}"
  description          = "Quantum Edge Redis cluster"
  engine_version       = "7.0"
  node_type            = var.node_type
  num_cache_clusters   = var.num_cache_clusters
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.this.name
  security_group_ids   = [aws_security_group.redis.id]

  automatic_failover_enabled = var.num_cache_clusters > 1
  at_rest_encryption_enabled = true
  # TLS off — existing code uses redis:// not rediss://
  transit_encryption_enabled = false

  tags = {
    Environment = var.environment
    Project     = "quantum-edge"
  }
}

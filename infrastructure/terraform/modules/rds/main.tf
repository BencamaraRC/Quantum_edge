resource "aws_db_subnet_group" "this" {
  name       = "qe-db-${var.environment}"
  subnet_ids = var.subnet_ids

  tags = {
    Environment = var.environment
    Project     = "quantum-edge"
  }
}

resource "aws_security_group" "rds" {
  name_prefix = "qe-rds-${var.environment}-"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    cidr_blocks     = [var.vpc_cidr]
    description     = "PostgreSQL from VPC"
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

resource "aws_db_parameter_group" "timescaledb" {
  name_prefix = "qe-pg16-${var.environment}-"
  family      = "postgres16"

  parameter {
    name  = "shared_preload_libraries"
    value = "timescaledb"
  }

  parameter {
    name  = "rds.allowed_extensions"
    value = "timescaledb"
  }

  tags = {
    Environment = var.environment
    Project     = "quantum-edge"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "this" {
  identifier           = "qe-timescaledb-${var.environment}"
  engine               = "postgres"
  engine_version       = "16"
  instance_class       = var.instance_class
  allocated_storage    = var.allocated_storage
  storage_type         = "gp3"
  db_name              = var.db_name
  username             = var.db_username
  manage_master_user_password = true
  parameter_group_name = aws_db_parameter_group.timescaledb.name
  db_subnet_group_name = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  multi_az             = true
  storage_encrypted    = true
  backup_retention_period = 7
  skip_final_snapshot  = false
  final_snapshot_identifier = "qe-final-${var.environment}"

  tags = {
    Environment = var.environment
    Project     = "quantum-edge"
  }
}

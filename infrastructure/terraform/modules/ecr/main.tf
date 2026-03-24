resource "aws_ecr_repository" "agent" {
  name                 = "quantum-edge/agent"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Environment = var.environment
    Project     = "quantum-edge"
  }
}

resource "aws_ecr_repository" "coordinator" {
  name                 = "quantum-edge/coordinator"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Environment = var.environment
    Project     = "quantum-edge"
  }
}

resource "aws_ecr_repository" "dashboard" {
  name                 = "quantum-edge/dashboard"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Environment = var.environment
    Project     = "quantum-edge"
  }
}

# Lifecycle policy — keep last 10 images
resource "aws_ecr_lifecycle_policy" "cleanup" {
  for_each   = toset(["quantum-edge/agent", "quantum-edge/coordinator", "quantum-edge/dashboard"])
  repository = each.key

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })

  depends_on = [
    aws_ecr_repository.agent,
    aws_ecr_repository.coordinator,
    aws_ecr_repository.dashboard,
  ]
}

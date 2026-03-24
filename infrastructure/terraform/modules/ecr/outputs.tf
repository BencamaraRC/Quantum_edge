output "agent_repository_url" {
  value = aws_ecr_repository.agent.repository_url
}

output "coordinator_repository_url" {
  value = aws_ecr_repository.coordinator.repository_url
}

output "dashboard_repository_url" {
  value = aws_ecr_repository.dashboard.repository_url
}

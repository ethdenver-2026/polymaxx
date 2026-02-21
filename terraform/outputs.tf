output "aws_region" {
  description = "AWS region used for this stack."
  value       = var.aws_region
}

output "instance_public_ip" {
  description = "Public IPv4 address of the Docker host EC2 instance."
  value       = aws_instance.docker_host.public_ip
}

output "ssh_command" {
  description = "SSH command template for the Docker host."
  value       = "ssh -i <private-key-path> ec2-user@${aws_instance.docker_host.public_ip}"
}

output "producer_endpoint" {
  description = "Base URL for the producer service."
  value       = "http://${aws_instance.docker_host.public_ip}:8000"
}

output "consumer_a_dashboard_url" {
  description = "Consumer A dashboard API URL."
  value       = "http://${aws_instance.docker_host.public_ip}:9866"
}

output "consumer_b_dashboard_url" {
  description = "Consumer B dashboard API URL."
  value       = "http://${aws_instance.docker_host.public_ip}:9867"
}

output "github_pat_secret_arn" {
  description = "Secrets Manager ARN for GitHub PAT."
  value       = aws_secretsmanager_secret.github_pat.arn
}

output "env_file_secret_arn" {
  description = "Secrets Manager ARN for .env content."
  value       = aws_secretsmanager_secret.env_file.arn
}

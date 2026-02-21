variable "project_name" {
  description = "Project name used for resource naming and tags."
  type        = string
  default     = "signal-market"
}

variable "aws_region" {
  description = "AWS region where infrastructure is provisioned."
  type        = string
  default     = "eu-west-2"
}

variable "vpc_cidr" {
  description = "CIDR block for the dedicated VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "public_subnet_cidr" {
  description = "CIDR block for the public subnet."
  type        = string
  default     = "10.42.1.0/24"
}

variable "public_subnet_cidr_b" {
  description = "CIDR block for the second public subnet."
  type        = string
  default     = "10.42.2.0/24"
}

variable "instance_type" {
  description = "EC2 instance type for the host."
  type        = string
  default     = "m6i.large"

  validation {
    condition     = contains(["t2.micro", "t3.micro", "t2.small", "t3.small", "t3.medium", "m6i.large"], var.instance_type)
    error_message = "instance_type must be one of t2.micro, t3.micro, t2.small, t3.small, t3.medium, or m6i.large."
  }
}

variable "ssh_ingress_cidrs" {
  description = "CIDR ranges allowed to SSH to the instance."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "app_ingress_cidrs" {
  description = "CIDR ranges allowed to access producer, consumer API, and dashboard ports."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "ssh_key_name" {
  description = "Name for the imported AWS key pair."
  type        = string
  default     = "cursor-ec2"
}

variable "ssh_public_key" {
  description = "SSH public key material used to create the AWS key pair."
  type        = string
  default     = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJywH4ZGk4nQPXZokBvRyUUpIfzc1qGTyeCMDWH9OyOd cursor-ec2"
}

variable "github_personal_access_token" {
  description = "GitHub PAT used by cloud-init to clone/pull the repository."
  type        = string
  sensitive   = true
}

variable "env_file_content" {
  description = "Full .env content stored in Secrets Manager for host bootstrap."
  type        = string
  default     = ""
  sensitive   = true
}

variable "github_repo_url" {
  description = "HTTPS git URL for repository bootstrap on host."
  type        = string
  default     = "https://github.com/ethdenver-2026/signal-market.git"
}

variable "github_repo_branch" {
  description = "Branch to checkout on host bootstrap."
  type        = string
  default     = "main"
}

variable "github_pat_secret_name" {
  description = "Secrets Manager name for GitHub PAT."
  type        = string
  default     = "signal-market/github-pat"
}

variable "env_secret_name" {
  description = "Secrets Manager name for rendered .env content."
  type        = string
  default     = "signal-market/env-file"
}

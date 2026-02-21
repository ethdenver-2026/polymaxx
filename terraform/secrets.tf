locals {
  env_secret_payload = var.env_file_content != "" ? var.env_file_content : (
    fileexists("${path.root}/../.env") ? file("${path.root}/../.env") : ""
  )
}

resource "aws_secretsmanager_secret" "github_pat" {
  name                    = var.github_pat_secret_name
  recovery_window_in_days = 0

  tags = {
    Name    = "${local.name_prefix}-github-pat"
    Project = var.project_name
  }
}

resource "aws_secretsmanager_secret_version" "github_pat" {
  secret_id     = aws_secretsmanager_secret.github_pat.id
  secret_string = var.github_personal_access_token

  lifecycle {
    precondition {
      condition     = length(trimspace(var.github_personal_access_token)) > 0
      error_message = "github_personal_access_token must be set and non-empty."
    }
  }
}

resource "aws_secretsmanager_secret" "env_file" {
  name                    = var.env_secret_name
  recovery_window_in_days = 0

  tags = {
    Name    = "${local.name_prefix}-env-file"
    Project = var.project_name
  }
}

resource "aws_secretsmanager_secret_version" "env_file" {
  secret_id     = aws_secretsmanager_secret.env_file.id
  secret_string = local.env_secret_payload

  lifecycle {
    precondition {
      condition     = length(trimspace(local.env_secret_payload)) > 0
      error_message = "env_file_content is empty and ../.env is missing or empty."
    }
  }
}

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "ec2_secrets_role" {
  name               = "${local.name_prefix}-ec2-secrets-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

data "aws_iam_policy_document" "ec2_read_secrets" {
  statement {
    effect = "Allow"
    actions = [
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetSecretValue",
    ]
    resources = [
      aws_secretsmanager_secret.github_pat.arn,
      aws_secretsmanager_secret.env_file.arn,
    ]
  }
}

resource "aws_iam_role_policy" "ec2_read_secrets" {
  name   = "${local.name_prefix}-ec2-read-secrets"
  role   = aws_iam_role.ec2_secrets_role.id
  policy = data.aws_iam_policy_document.ec2_read_secrets.json
}

resource "aws_iam_instance_profile" "docker_host" {
  name = "${local.name_prefix}-ec2-profile"
  role = aws_iam_role.ec2_secrets_role.name
}

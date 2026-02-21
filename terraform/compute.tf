data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-x86_64"
}

resource "aws_key_pair" "ec2_access" {
  key_name   = var.ssh_key_name
  public_key = var.ssh_public_key

  tags = {
    Name    = "${local.name_prefix}-keypair"
    Project = var.project_name
  }
}

resource "aws_instance" "docker_host" {
  ami                         = data.aws_ssm_parameter.al2023_ami.value
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  key_name                    = aws_key_pair.ec2_access.key_name
  iam_instance_profile        = aws_iam_instance_profile.docker_host.name
  vpc_security_group_ids      = [aws_security_group.app.id]
  associate_public_ip_address = true

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    aws_region             = var.aws_region
    github_pat_secret_name = aws_secretsmanager_secret.github_pat.name
    env_secret_name        = aws_secretsmanager_secret.env_file.name
    github_repo_url        = var.github_repo_url
    github_repo_branch     = var.github_repo_branch
  })

  depends_on = [
    aws_secretsmanager_secret_version.github_pat,
    aws_secretsmanager_secret_version.env_file,
    aws_iam_role_policy.ec2_read_secrets,
  ]

  tags = {
    Name    = "${local.name_prefix}-docker-host"
    Project = var.project_name
  }
}

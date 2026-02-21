terraform {
  required_version = ">= 1.6.0"

  backend "s3" {
    bucket  = "ethdenver2026"
    key     = "signal-market/terraform.tfstate"
    region  = "eu-west-2"
    encrypt = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

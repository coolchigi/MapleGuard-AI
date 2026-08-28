terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.40"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4"
    }
  }
}

provider "aws" {
  region = var.region

  # Every resource is tagged, so `make aws-down` (terraform destroy) removes a clearly-scoped
  # set and nothing is orphaned.
  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Component = "mapleguard-monitor"
    }
  }
}

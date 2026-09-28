# ThinkiX Hybrid Zero Trust - Terraform Root Configuration
# Hybrid AWS and Azure infrastructure for the ThinkiX prototype.
#
# This file defines the two cloud providers (AWS + Azure) used to
# simulate the "Cloud Zone" of the 5-zone hybrid architecture.
# State is stored remotely in HCP Terraform Cloud for shared management.

terraform {
  required_version = ">= 1.6.0"

  # ---- Remote state (HCP Terraform Cloud) ----
  cloud {
    organization = "thinkix-zerotrust"

    workspaces {
      name = "thinkix-hybrid-zt"
    }
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.90"
    }
  }
}

# ---- AWS Provider ----
# Auth: run `aws configure` locally with an IAM user's access key
# (never use root account keys). Region = Sydney to match your team location.
provider "aws" {
  region = "ap-southeast-2"

  default_tags {
    tags = {
      Project = "ThinkiX-ZeroTrust"
      Managed = "Terraform"
    }
  }
}

# ---- Azure Provider ----
# Auth: run `az login` locally, or use a Service Principal for CI/CD.
provider "azurerm" {
  features {}
}

# Per-environment root module. Identical across dev/uat/prod - the env
# identity and project come from direnv (TF_VAR_env, TF_VAR_project_id in
# .envrc), and each directory keeps its OWN state file, so applies are
# isolated per environment. The actual resources live in the shared
# ../modules/warehouse module.
terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
  # Local state for this learning project. Prod would use a remote backend
  # (a GCS bucket) per environment so state is shared, locked, and durable.
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "env" {
  type        = string
  description = "Environment name; supplied by direnv as TF_VAR_env."
}

variable "project_id" {
  type        = string
  description = "GCP project id; supplied by direnv as TF_VAR_project_id."
}

variable "region" {
  type        = string
  description = "Default provider region."
  default     = "europe-west1"
}

variable "bq_location" {
  type        = string
  description = "BigQuery dataset location."
  default     = "EU"
}

variable "enable_service_account" {
  type        = bool
  description = "Create the least-privilege SA (needs billing). False in sandbox."
  default     = true
}

module "warehouse" {
  source                 = "../modules/warehouse"
  env                    = var.env
  project_id             = var.project_id
  bq_location            = var.bq_location
  enable_service_account = var.enable_service_account
}

output "datasets" {
  description = "Dataset ids created for this environment."
  value       = module.warehouse.datasets
}

output "service_account_email" {
  value = module.warehouse.service_account_email
}

output "sa_key_path" {
  value = module.warehouse.sa_key_path
}

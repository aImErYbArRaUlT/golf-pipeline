variable "env" {
  type        = string
  description = "Environment name (dev/uat/prod). Prefixes every dataset id."
  validation {
    condition     = contains(["dev", "uat", "prod"], var.env)
    error_message = "env must be one of: dev, uat, prod."
  }
}

variable "project_id" {
  type        = string
  description = "GCP project id that holds this environment's datasets."
}

variable "bq_location" {
  type        = string
  description = "BigQuery dataset location (multi-region like EU/US, or a region)."
  default     = "EU"
}

variable "layers" {
  type        = list(string)
  description = "Medallion layers; each becomes a <env>_<layer> dataset."
  default     = ["bronze", "silver", "gold"]
}

variable "enable_service_account" {
  type        = bool
  description = <<-EOT
    Create the least-privilege service account + key (needs billing). In
    BigQuery Sandbox set this false: the SA stays defined as the documented
    production pattern, and the pipeline uses your own ADC instead.
  EOT
  default     = true
}

variable "sa_account_id" {
  type        = string
  description = "Account id (local part) for the pipeline service account."
  default     = "golf-pipeline"
}

variable "key_output_path" {
  type        = string
  description = "Local path to write the generated SA key JSON. Gitignored."
  default     = "sa-key.json"
}

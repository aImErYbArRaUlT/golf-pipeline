output "service_account_email" {
  description = "Pipeline SA email (null in sandbox / SA disabled)."
  value       = one(google_service_account.pipeline[*].email)
}

output "datasets" {
  description = "Created BigQuery dataset ids for this environment."
  value       = [for d in google_bigquery_dataset.medallion : d.dataset_id]
}

output "sa_key_path" {
  description = "Local path of the generated SA key (null when SA disabled)."
  value       = one(local_sensitive_file.sa_key[*].filename)
}

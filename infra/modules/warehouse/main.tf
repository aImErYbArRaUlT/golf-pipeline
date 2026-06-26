# ─────────────────────────────────────────────────────────────
# Medallion datasets, namespaced per environment: <env>_<layer>
# (dev_bronze, dev_silver, ...). One project can hold every env's
# datasets side by side; pointing an env at its own project later is a
# one-line change to that env's project_id - no code change here.
# ─────────────────────────────────────────────────────────────
resource "google_bigquery_dataset" "medallion" {
  for_each = toset(var.layers)

  dataset_id  = "${var.env}_${each.value}"
  project     = var.project_id
  location    = var.bq_location
  description = "Golf pipeline ${var.env} ${each.value} layer."
  labels      = { env = var.env, layer = each.value }

  # Safe to destroy in this project; a prod warehouse would not set this.
  delete_contents_on_destroy = true
}

# ─────────────────────────────────────────────────────────────
# Least-privilege service account (gated; off in sandbox). The account id
# is env-suffixed so multiple environments can coexist in one project.
# ─────────────────────────────────────────────────────────────
resource "google_service_account" "pipeline" {
  count        = var.enable_service_account ? 1 : 0
  account_id   = "${var.sa_account_id}-${var.env}"
  display_name = "Golf pipeline ${var.env} (ingestion + dbt)"
  project      = var.project_id
}

# May run BigQuery jobs (load + query). Grants no data access by itself.
resource "google_project_iam_member" "job_user" {
  count   = var.enable_service_account ? 1 : 0
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.pipeline[0].email}"
}

# Data access scoped to THIS env's datasets only - least privilege.
resource "google_bigquery_dataset_iam_member" "data_editor" {
  for_each = var.enable_service_account ? google_bigquery_dataset.medallion : {}

  dataset_id = each.value.dataset_id
  project    = var.project_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.pipeline[0].email}"
}

# SA key -> local gitignored file, read via GOOGLE_APPLICATION_CREDENTIALS.
# Lands in tfstate too (gitignored); prod would use Workload Identity.
resource "google_service_account_key" "pipeline" {
  count              = var.enable_service_account ? 1 : 0
  service_account_id = google_service_account.pipeline[0].name
}

resource "local_sensitive_file" "sa_key" {
  count           = var.enable_service_account ? 1 : 0
  content         = base64decode(google_service_account_key.pipeline[0].private_key)
  filename        = var.key_output_path
  file_permission = "0600"
}

# A module declares which providers it needs, but never configures them -
# the provider block lives in the calling root module (each env dir). This
# keeps the module reusable across environments and projects.
terraform {
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
}

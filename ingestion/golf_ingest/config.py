"""Environment-backed configuration.

Every secret and environment-specific value is read from the environment
(loaded from a local .env via python-dotenv), never hardcoded. This module
is the single place that touches os.environ.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load .env once on import. Harmless if the file is absent (e.g. in CI,
# where real env vars are injected instead).
load_dotenv()


def _require(name: str) -> str:
    """Return a required env var or fail loudly with a clear message."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class MinioConfig:
    endpoint: str
    access_key: str
    secret_key: str
    bucket_bronze: str

    @classmethod
    def from_env(cls) -> MinioConfig:
        return cls(
            endpoint=os.environ.get("MINIO_ENDPOINT", "http://localhost:9000"),
            access_key=_require("MINIO_ROOT_USER"),
            secret_key=_require("MINIO_ROOT_PASSWORD"),
            bucket_bronze=os.environ.get("MINIO_BUCKET_BRONZE", "bronze"),
        )


@dataclass(frozen=True)
class BigQueryConfig:
    project_id: str
    location: str
    env: str
    dataset_bronze: str

    @classmethod
    def from_env(cls) -> BigQueryConfig:
        # GOLF_ENV (set by direnv) selects the environment; datasets are
        # namespaced <env>_<layer> to match the OpenTofu warehouse module.
        env = os.environ.get("GOLF_ENV", "dev")
        return cls(
            project_id=_require("GCP_PROJECT_ID"),
            location=os.environ.get("GCP_LOCATION", "EU"),
            env=env,
            dataset_bronze=os.environ.get("BQ_DATASET_BRONZE", f"{env}_bronze"),
        )

"""Load bronze Parquet into BigQuery.

The load is idempotent by design: WRITE_TRUNCATE replaces the source's
bronze table on every run, so re-running the pipeline never duplicates rows.
At bronze, one source == one table; conforming/union happens downstream.

Auth: the BigQuery client uses Application Default Credentials, which here
resolve to the service-account key referenced by GOOGLE_APPLICATION_CREDENTIALS
(created by OpenTofu). No credentials are passed in code.
"""

from __future__ import annotations

import io

from google.cloud import bigquery

from .config import BigQueryConfig


def load_parquet(cfg: BigQueryConfig, parquet_bytes: bytes, table_name: str) -> str:
    """Load Parquet bytes into `bronze.<table_name>`, replacing it.

    Returns the fully-qualified table id. Schema is autodetected from the
    Parquet file (all string columns at bronze).
    """
    client = bigquery.Client(project=cfg.project_id, location=cfg.location)
    table_id = f"{cfg.project_id}.{cfg.dataset_bronze}.{table_name}"

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        autodetect=True,
    )

    job = client.load_table_from_file(io.BytesIO(parquet_bytes), table_id, job_config=job_config)
    job.result()  # block until the load completes; raises on failure
    return table_id

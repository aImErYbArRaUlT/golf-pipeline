# Airflow image for the golf pipeline.
# dbt and the ingestion deps are installed into a SEPARATE venv so they can't
# fight Airflow's own pinned dependencies (dbt pulls jinja2/protobuf/etc. that
# would otherwise clash). The DAG calls this venv's python/dbt by absolute path.
FROM apache/airflow:2.10.5-python3.12

# Isolated venv for dbt + ingestion runtime (kept out of Airflow's environment).
RUN python -m venv /home/airflow/dbt-venv \
    && /home/airflow/dbt-venv/bin/pip install --no-cache-dir \
        "dbt-bigquery>=1.8" \
        "pandas>=2.2" \
        "pyarrow>=16.0" \
        "boto3>=1.34" \
        "google-cloud-bigquery>=3.25" \
        "requests>=2.32" \
        "python-dotenv>=1.0"

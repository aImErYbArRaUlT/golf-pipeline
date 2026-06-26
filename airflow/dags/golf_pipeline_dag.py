"""Golf pipeline DAG - the whole thing, orchestrated.

Flow: ingest each source (in parallel) into bronze, then dbt seed -> run -> test
as a single gated quality pipeline. dbt test is the final gate: if a data
contract fails, the run fails.

Every step is idempotent, so retries and re-runs never duplicate data:
  * ingestion loads bronze with WRITE_TRUNCATE (one table per source),
  * dbt models are rebuilt from scratch each run.

dbt and ingestion run from an isolated venv (see the Dockerfile) by absolute
path, so Airflow's own dependencies stay untouched. Config (project id, MinIO
endpoint, ADC) comes from the container environment set in docker-compose.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.models.dag import DAG
from airflow.operators.bash import BashOperator

REPO = "/opt/golf"
PY = "/home/airflow/dbt-venv/bin/python"
DBT = "/home/airflow/dbt-venv/bin/dbt"
SOURCES = ["trackman", "foresight", "caddieset"]

default_args = {
    "owner": "data-eng",
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
    "depends_on_past": False,
}

with DAG(
    dag_id="golf_pipeline",
    description="Ingest launch-monitor sources, then dbt seed/run/test.",
    default_args=default_args,
    start_date=pendulum.datetime(2024, 1, 1, tz="UTC"),
    schedule=None,  # triggered manually (or set a cron later)
    catchup=False,
    max_active_runs=1,
    tags=["golf", "elt", "dbt"],
) as dag:
    # One ingestion task per source; these run in parallel. PYTHONPATH points at
    # the ingestion package; all other config is inherited from the environment.
    ingests = [
        BashOperator(
            task_id=f"ingest_{src}",
            bash_command=(
                f"cd {REPO} && PYTHONPATH={REPO}/ingestion "
                f"{PY} -m golf_ingest.ingest --source {src}"
            ),
        )
        for src in SOURCES
    ]

    dbt_seed = BashOperator(
        task_id="dbt_seed",
        bash_command=f"cd {REPO}/dbt && {DBT} seed --target dev --profiles-dir .",
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=f"cd {REPO}/dbt && {DBT} run --target dev --profiles-dir .",
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=f"cd {REPO}/dbt && {DBT} test --target dev --profiles-dir .",
    )

    # all sources land -> seed -> build -> test (the quality gate)
    ingests >> dbt_seed >> dbt_run >> dbt_test

# Golf pipeline - command runner.
# Run `just` with no args to list recipes. Recipes are the single source
# of truth for how the project is operated; the README points here.

# Load .env into every recipe (GCP_PROJECT_ID, MinIO creds, GOLF_ENV, ...).
set dotenv-load := true

# Show available recipes.
default:
    @just --list

# ── Setup ────────────────────────────────────────────────────
# Install Python deps (runtime + dev) into a uv-managed venv.
install:
    uv sync --group dev

# Install all dependency groups (dev + dbt + spark).
install-all:
    uv sync --group dev --group dbt --group spark

# Install git pre-commit hooks (linters, formatters, secret scanner).
hooks:
    uv run pre-commit install

# ── Docker stack ─────────────────────────────────────────────
# Start the local stack (MinIO now; Airflow/Spark added in later phases).
up:
    docker compose up -d

# Stop the stack, keeping volumes.
down:
    docker compose down

# Stop the stack and delete volumes (wipes local MinIO data).
nuke:
    docker compose down -v

# ── Infrastructure (OpenTofu, per environment) ───────────────
# `direnv exec` loads infra/<env>/.envrc (project, env, SA toggle) for the
# command, so this works from the repo root.
# Provision an environment's BigQuery datasets, e.g. `just infra-apply prod`.
infra-apply env="dev":
    cd infra/{{env}} && direnv exec . tofu init && direnv exec . tofu apply

# Tear down an environment's infrastructure.
infra-destroy env="dev":
    cd infra/{{env}} && direnv exec . tofu destroy

# Show an environment's outputs (dataset ids, SA email).
infra-output env="dev":
    cd infra/{{env}} && direnv exec . tofu output

# ── Pipeline ─────────────────────────────────────────────────
# Run ingestion: CSV -> Parquet -> MinIO -> BigQuery <env>_bronze.
ingest source="trackman" env="dev":
    GOLF_ENV={{env}} uv run python -m golf_ingest.ingest --source {{source}}

# Ingest a personal launch-monitor session (any export) -> <env>_bronze.manual_raw.
# Conforms the headers, stamps the player, lands it; then run `just dbt-run <env>`
# and it shows up as a player in the app's "My ingested data".
ingest-session file player env="dev":
    GOLF_ENV={{env}} uv run --group modeling python -m modeling.ingest_session --file "{{file}}" --player "{{player}}"

# Run dbt models for an environment (writes to <env>_silver / <env>_gold).
dbt-run env="dev":
    cd dbt && DBT_PROFILES_DIR=. uv run dbt run --target {{env}}

# Run dbt tests (the data-quality gate).
dbt-test env="dev":
    cd dbt && DBT_PROFILES_DIR=. uv run dbt test --target {{env}}

# Build + test in one step.
dbt-build env="dev":
    cd dbt && DBT_PROFILES_DIR=. uv run dbt build --target {{env}}

# Check the connection and project parse.
dbt-debug env="dev":
    cd dbt && DBT_PROFILES_DIR=. uv run dbt debug --target {{env}}

# Generate and serve the dbt docs site (model docs + lineage DAG) at :8085.
dbt-docs env="dev" port="8085":
    cd dbt && DBT_PROFILES_DIR=. uv run dbt docs generate --target {{env}}
    cd dbt && DBT_PROFILES_DIR=. uv run dbt docs serve --target {{env}} --port {{port}}

# ── Airflow (Phase 4) ────────────────────────────────────────
# Build + start Airflow (and MinIO) via the "airflow" compose profile.
airflow-up:
    docker compose --profile airflow up -d --build

# Stop Airflow services (keeps volumes).
airflow-down:
    docker compose --profile airflow down

# Trigger the full pipeline DAG.
dag-trigger:
    docker compose exec airflow airflow dags trigger golf_pipeline

# Tail the Airflow scheduler/standalone logs.
airflow-logs:
    docker compose logs -f airflow

# List DAGs / show import errors (quick health check).
dag-check:
    docker compose exec airflow airflow dags list-import-errors

# ── AI schema mapping (Phase 7) ──────────────────────────────
# Propose a mapping for a source into the common schema (advisory; needs
# ANTHROPIC_API_KEY and the `ai` group). Writes a draft for human review.
ai-map source url="":
    uv run --group ai python -m golf_ingest.ai_mapping --source {{source}} {{ if url != "" { "--url " + url } else { "" } }} --out {{source}}_mapping.draft.json

# ── Spark (Phase 5) ──────────────────────────────────────────
# Run the distributed silver transform (reads bronze from MinIO, writes silver).
spark-silver:
    docker compose --profile spark run --rm spark

# ── Modeling - Strategy Engine ───────────────────────────────
# Stage A: calibrate the physics engine against measured carry, then plot a shot.
calibrate:
    uv run --group modeling python -m modeling.run_calibration

# Synthetic bag from tour means + a skill level (clean demo data, no warehouse).
synth tour="pga" skill="scratch":
    uv run --group modeling python -m modeling.run_synthetic {{tour}} {{skill}}

# Stage B: Monte-Carlo per-club shot dispersion, plotted as landing ovals.
dispersion:
    uv run --group modeling python -m modeling.run_dispersion

# Stage C: strokes-gained scoring - expected strokes per club vs a tight benchmark.
# Pass a skill (tour/scratch/amateur) to run on a clean synthetic bag instead of real data.
scoring skill="":
    uv run --group modeling python -m modeling.run_scoring {{skill}}

# Stage E: shot-selection optimizer on a 2-D hole - best club + aim point, vs the flag.
# Pass a skill (tour/scratch/amateur) to run on a clean synthetic bag instead of real data.
optimize skill="":
    uv run --group modeling python -m modeling.run_optimize {{skill}}

# Whole-hole MDP planner - best shot sequence on a 2-D hole, with a value heatmap.
plan skill="tour":
    uv run --group modeling python -m modeling.run_plan {{skill}}

# Plan a real course hole (Torrey Pines South, from OSM outlines) and render it.
course hole="18" skill="tour":
    uv run --group modeling python -m modeling.run_course {{hole}} {{skill}}

# Stage F: interactive Streamlit app over the whole engine (skill, hole, conditions).
app port="8501":
    uv run --group modeling --group app streamlit run modeling/app.py --server.port {{port}}

# Validate the engine against TrackMan's published PGA Tour carries (whole bag).
benchmark:
    uv run --group modeling python -m modeling.run_benchmark

# Disposable: scrape an HTML benchmark table to CSV for review. See benchmarks/SOURCES.md.
collect-benchmarks *args:
    uv run --group collect python -m modeling.benchmarks.collect {{args}}

# Run the modeling unit tests (physics, batch, calibration, dispersion, scoring, optimize).
test-modeling:
    uv run --group modeling pytest modeling/tests

# ── Quality ──────────────────────────────────────────────────
# Lint Python (ruff) and SQL (sqlfluff).
lint:
    uv run ruff check .
    uv run sqlfluff lint dbt/models || true

# Format Python (black + ruff import sort) and SQL.
fmt:
    uv run black .
    uv run ruff check --fix .
    uv run sqlfluff fix dbt/models || true

# Run Python unit tests.
test:
    uv run pytest

# Run every pre-commit hook against all files.
check:
    uv run pre-commit run --all-files

# ── Housekeeping ─────────────────────────────────────────────
# Remove local build/run artifacts (keeps committed files).
clean:
    rm -rf data/raw data/parquet dbt/target dbt/logs .ruff_cache .pytest_cache

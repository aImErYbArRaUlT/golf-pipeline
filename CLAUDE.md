# CLAUDE.md

Standards and conventions for this repository. Read before making changes.
These rules are deliberate; follow them unless there's a clear, stated reason
not to.

## What this project is

A production-shaped, multi-source golf launch-monitor data pipeline. It ingests
shot data from different launch monitors (TrackMan, Foresight/Garmin, …),
**conforms** each source into one common schema, and models it with a medallion
architecture (bronze → silver → gold). It runs locally in Docker as a faithful
simulation of a GCP/dbt/Airflow stack.

The signature design idea: **source-agnostic conforming**. Each source maps into
the common schema in its own staging model, so adding a new launch monitor is a
new staging model (plus a registry entry) - nothing downstream changes.

## Tech stack

- **Python 3.12**, managed with **uv** (never pip/poetry/conda directly).
- **just** - command runner; the justfile is the source of truth for operations.
- **OpenTofu** (`tofu`) - infrastructure as code.
- **dbt Core** (BigQuery adapter) - transformations.
- **BigQuery** - warehouse (runs in Sandbox: no billing).
- **MinIO** - local S3-compatible object storage (simulates S3/GCS).
- **PySpark** - distributed silver-layer transform (later phase).
- **Apache Airflow** - orchestration (later phase).
- **direnv** - per-environment shell context.

## Repository layout

```
ingestion/golf_ingest/   Python ingestion package (CSV -> Parquet -> MinIO -> bronze)
infra/
  modules/warehouse/     Reusable OpenTofu module (datasets + optional SA)
  dev/ uat/ prod/         Per-environment root modules (own state + .envrc)
dbt/                     dbt project (staging / silver / gold + tests)
airflow/dags/            Airflow DAGs
spark/                   PySpark jobs
tests/                   Python unit tests
data/                    Local raw/parquet (gitignored; samples allowed)
docs/                    Architecture, data-model, and codebase-tour docs
```

## Commands (use the justfile)

Run `just --list` for the full set. Common ones:

```sh
just install            # uv sync runtime + dev deps
just hooks              # install pre-commit hooks
just up / just down     # start / stop the Docker stack (MinIO)
just infra-apply <env>  # provision an environment's BigQuery datasets
just ingest <source> <env>   # run ingestion into <env>_bronze
just dbt-run <env> / just dbt-test <env>
just lint / just fmt / just test / just check
```

Recipes default `env` to `dev`. Don't add ad-hoc shell scripts when a recipe
fits - extend the justfile instead.

## Dev environment, MCP, and skills

- The toolchain is pinned in `flake.nix`; with Nix + nix-direnv it's provisioned
  on `cd` (Windows: WSL2). `.envrc` falls back to host tools without nix-direnv.
- A **`bigquery` MCP server** (`.mcp.json`, Google's MCP Toolbox via the dev
  shell) is available for warehouse work - prefer its tools over shelling to `bq`.
  Follow the `bigquery` skill: introspect before querying, stay read-only.
- Project skills (`.claude/skills/`) and the `data-engineer` agent
  (`.claude/agents/`) are committed and shared. Use `add-source` when onboarding
  a launch monitor.

## Environments

- Environments are `dev`, `uat`, `prod`. The active one is `GOLF_ENV` (default `dev`).
- BigQuery datasets are namespaced **`<env>_<layer>`** (e.g. `dev_bronze`,
  `prod_gold`). Never hardcode a bare `bronze`/`silver`/`gold` name.
- **direnv** drives env context: the repo-root `.envrc` loads `.env`; each
  `infra/<env>/.envrc` sets `TF_VAR_env` and `TF_VAR_project_id`. `.envrc` files
  are committed (they contain no secrets); `direnv allow` once per directory.
- All three envs currently share one GCP project via dataset prefixing. The code
  is structured so pointing an env at its own project later is a one-variable
  change (per-env `project_id`) - keep it that way.

## Authentication

- Local/sandbox auth is the developer's **Application Default Credentials** (ADC):
  `gcloud auth application-default login` + set the quota project. The BigQuery
  client and dbt use ADC automatically when `GOOGLE_APPLICATION_CREDENTIALS` is unset.
- A **least-privilege service account** is fully defined in the warehouse module
  but toggled off in sandbox (`enable_service_account = false`, since SA keys need
  billing). With billing, flip it on and reference the generated key via
  `GOOGLE_APPLICATION_CREDENTIALS`. The SA stays the documented production pattern.

## The common schema

Every source's staging model conforms to exactly this column set:

```
shot_id, source, player, club, session_date,
ball_speed_mph, club_speed_mph, smash_factor, launch_angle_deg,
spin_rate_rpm, carry_yards, total_yards, side_dispersion,
spin_axis_deg, launch_direction_deg
```

Staging is where raw column names are renamed and units are normalized
(mph/ms, yards/meters). If a source lacks a field (e.g. TrackMan has no
player/date), default or synthesize it in that source's staging model and
document the choice.

## Secret safety (non-negotiable)

- **Never commit** secrets: `.env`, `*.tfvars`, `*.tfstate*`, `*-key.json`,
  credentials. These are gitignored; keep them so. Only `.env.example` and
  `*.tfvars.example` (placeholders) are tracked.
- **No credentials in code, ever.** Read everything from environment variables
  (see `ingestion/golf_ingest/config.py` - the single place that touches the env).
- **gitleaks** runs as a pre-commit hook and is the hard guarantee. Do not bypass
  hooks (`--no-verify`) to force a commit through.
- OpenTofu **state is gitignored** (it can contain secrets); the provider **lock
  file (`.terraform.lock.hcl`) IS committed** for reproducibility.
- Before any push, confirm `git status` shows no env/key/state files.

## Git conventions

- **Conventional Commits**: `type(scope): description`. Types: `feat`, `fix`,
  `docs`, `chore`, `refactor`, `test`, `ci`.
- **Atomic commits** - one logical change each. Split unrelated changes.
- Commit messages describe **what changed and why**, not how or by whom. No
  co-author trailers, no tool attribution, no emojis.
- **Branching**: feature branches off `main`; merge PR-style with `--no-ff` to
  preserve topology. No direct commits to `main`.
- Verify behavior before committing a `feat` (run it / test it), so commits
  represent working states.

## Python standards

- Manage deps with uv: `uv add <pkg>`, dependency groups for phase-specific tools
  (`dev`, `dbt`, `spark`). Commit `pyproject.toml` and `uv.lock`.
- Lint/format with **ruff** (line length 100; rules E,F,I,UP,B) and **black**
  (line length 100). Both run in pre-commit.
- Type hints on function signatures; `from __future__ import annotations` at the
  top of modules. Concise docstrings explaining intent, not restating code.
- Use frozen dataclasses for config; fail loudly on missing required env vars.
- Keep modules single-responsibility (see the ingestion package: `config`,
  `sources`, `transform`, `storage`, `loader`, `ingest`).

## SQL / dbt standards

- Lint with **sqlfluff** (BigQuery dialect, lowercase keywords/identifiers).
- Every model and key column gets a one-line YAML `description:`.
- **dbt tests are data contracts**, not afterthoughts: `not_null` and `unique`
  on `shot_id`, `accepted_values`/range checks on metrics, relationship tests on
  dims. Tests are the final quality gate.
- dbt targets map to environments (`dev`/`uat`/`prod`) and write to `<env>_*`
  datasets via `GOLF_ENV`.
- gold is a star schema: `fct_shots` (grain: one row per shot) + `dim_player`,
  `dim_club`, `dim_session`.

## OpenTofu standards

- Resource logic lives in **modules** (`infra/modules/`). Modules declare
  `required_providers` but **never** contain a `provider` block - the calling
  root module (per-env dir) configures the provider.
- Each environment is its own root module with its **own state**.
- **Least privilege**: grant `roles/bigquery.jobUser` at project level (run jobs,
  no data access) and `roles/bigquery.dataEditor` **scoped per-dataset** - never
  project-wide data roles.
- `tofu fmt` and `tofu validate` before committing infra changes.
- `apply`/`destroy` via the justfile keep interactive approval; don't add
  `-auto-approve` to recipes.

## Data engineering principles

- **Idempotent loads**: re-running never duplicates. Bronze uses
  `WRITE_TRUNCATE` per source table; downstream uses MERGE / partition overwrite.
  Never blind-append.
- **Bronze is raw**: land data faithfully. The only permitted bronze changes are
  mechanical - skip a source's units row, sanitize headers to snake_case
  (BigQuery requires it), add lineage columns (`_source`, `_ingested_at_utc`).
  All renaming and unit conversion happens in staging, not bronze.
- **Source-agnostic by design**: adding a launch monitor = a new entry in
  `ingestion/golf_ingest/sources.py` + a new dbt staging model. Nothing else.

### Adding a new source

1. Add a `Source(...)` entry to `SOURCES` in `sources.py` (URL, encoding,
   whether it has a units row, bronze table name).
2. `just ingest <source> <env>` to land it in `<env>_bronze`.
3. Add `stg_<source>.sql` mapping its raw columns + units into the common schema.
4. Union it into `silver_shots`; confirm tests still pass.

## Documentation

- Write for technical readers: short, direct, scannable. No tutorial filler, no
  marketing tone. Explain the *why* of a design choice over the *what* of the code.
- Diagrams in Mermaid (renders on GitHub): light fills, dark same-hue borders,
  explicit black text, colored by meaning (sources/storage/warehouse/transform).

## Build phases (roadmap)

0. Repo foundation · 1. Manual pipeline → bronze · 2. dbt (staging/silver/gold +
tests) · 3. Second source (conforming) · 3.5. Enrichment/metadata + SCD2 dims
(see `docs/data-model.md`) · 4. Airflow orchestration · 5. PySpark
silver transform · 6. CI + docs polish · 7. (optional) AI-assisted schema mapping.

Each phase leaves a working artifact and is built in order.

---
name: add-source
description: Add a new launch-monitor data source end to end - registry entry, bronze ingest, dbt staging model mapping to the common schema, and tests. Use when integrating a new launch monitor or CSV source into the pipeline.
---

# Add a new launch-monitor source

The pipeline is source-agnostic: a new source is a registry entry plus a new
dbt staging model. Nothing downstream of staging changes. Follow these steps.

## 1. Register the source (ingestion)

In `ingestion/golf_ingest/sources.py`, add a `Source(...)` to `SOURCES`:

```python
"<name>": Source(
    name="<name>",
    url_env_var="<NAME>_CSV_URL",
    has_units_row=True,        # most launch monitors emit a units row on line 2
    encoding="utf-8-sig",      # use utf-8-sig if the export has a BOM
    bronze_table="<name>_raw",
    default_url="https://raw.githubusercontent.com/.../export.csv",
),
```

Inspect the real CSV first (header row, units row, delimiter, encoding/BOM,
missing-value convention) so these flags are correct. Add a matching
`# <NAME>_CSV_URL=` line to `.env.example`.

## 2. Land it in bronze

```sh
just ingest <name> dev      # CSV -> Parquet -> MinIO -> dev_bronze.<name>_raw
```

Then confirm with the `bigquery` skill: row count, columns sanitized to
snake_case, `_source` present.

## 3. Conform it (dbt staging)

Add `dbt/models/staging/stg_<name>.sql` selecting from `<name>_raw` and mapping
its raw columns + units into the **common schema** (exactly these columns):

```
shot_id, source, player, club, session_date,
ball_speed_mph, club_speed_mph, smash_factor, launch_angle_deg,
spin_rate_rpm, carry_yards, total_yards, side_dispersion
```

- Rename raw columns; convert units (m/s→mph, m→yards, etc.) so every source
  lands in the same units.
- If the source lacks a field (e.g. no player/date), default or synthesize it
  and leave a comment explaining the choice.
- Generate `shot_id` consistently with the other staging models.

## 4. Union + test

- Add the model to the `silver_shots` union (with its `source` value).
- Add `stg_<name>` to `dbt/models/staging/schema.yml` with a one-line
  `description:` per model/key column, plus `not_null`/`unique`/range tests.
- Run `just dbt-run dev` and `just dbt-test dev`; confirm both sources conform
  and all tests pass.

## 5. Commit

Conventional commit, e.g. `feat(dbt): add <name> source and conform to common schema`.

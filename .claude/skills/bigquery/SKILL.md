---
name: bigquery
description: Best practices for querying this project's BigQuery warehouse via the `bigquery` MCP server. Use when inspecting datasets/tables, validating ingestion or dbt outputs, or writing and running SQL against BigQuery.
---

# Working with BigQuery (this project)

Use the **`bigquery` MCP server** tools (`list_dataset_ids`, `list_table_ids`,
`get_dataset_info`, `get_table_info`, `execute_sql`, …) instead of shelling out
to `bq`. Auth is the developer's ADC; the server reads `BIGQUERY_PROJECT` /
`BIGQUERY_LOCATION` from the environment.

## Conventions

- **Dataset names are `<env>_<layer>`** - `dev_bronze`, `dev_silver`, `dev_gold`,
  `uat_*`, `prod_*`. Never assume a bare `bronze`. Confirm the active env
  (`GOLF_ENV`, default `dev`) before querying.
- Always use fully-qualified names: `` `project.dataset.table` ``.
- BigQuery has reserved words - alias them (e.g. `count(*) AS n_rows`, not `rows`).

## Practices

- **Introspect before querying.** Use `list_dataset_ids` → `list_table_ids` →
  `get_table_info` to learn the schema, rather than guessing column names.
- **Stay read-only.** The warehouse is managed: datasets by OpenTofu, tables by
  dbt and the ingestion loader. Do not `CREATE`/`DROP`/`DELETE`/`INSERT` by hand
  - change the dbt model or the loader and re-run instead.
- **Keep scans small.** Prefer explicit columns over `SELECT *`, add `LIMIT` when
  sampling, and filter early. (Sandbox is free under the 1 TB/month query cap,
  but treat scanned bytes as if they cost - it's the prod habit.)
- **Validate, don't assume.** After ingestion: `count(*)` and
  `count(distinct _source)`. After dbt: check `<env>_silver` / `<env>_gold` row
  counts and that `shot_id` is unique and non-null (the dbt tests enforce this,
  but a quick query confirms a run landed).

## Sandbox limits to remember

No billing attached. Tables auto-expire after 60 days, there's no streaming
insert, and load/query stay within the free tier. Everything is rebuildable:
`just infra-apply <env>` recreates datasets, `just ingest` + `just dbt-run`
repopulate them.

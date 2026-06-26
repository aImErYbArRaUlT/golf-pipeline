# AGENTS.md

Guidance for AI coding agents working in this repository (Claude Code, Cursor, Aider,
Codex, and others). Human contributors should read CONTRIBUTING.md.

## What this is

A multi-source golf launch-monitor data pipeline (bronze, silver, gold) plus a
strokes-gained strategy engine. Python 3.12, managed with uv. Operations run through the
justfile, which is the source of truth.

## Setup

- `just install` syncs runtime and dev dependencies with uv.
- `just hooks` installs the pre-commit hooks (ruff, black, sqlfluff, gitleaks).

## Commands

- `just check` runs lint, format check, and tests. Run it before committing.
- `just lint`, `just fmt`, `just test` for the individual steps.
- `uv run pytest modeling/tests` for the strategy-engine tests.
- `just dbt-run dev` and `just dbt-test dev` for the transformations.
- `just --list` for the full set.

## Conventions

- Lint and format with ruff and black (line length 100); SQL with sqlfluff. All run in
  pre-commit and CI, so keep them green.
- Conventional Commits: `type(scope): description`. One logical change per commit.
- Feature branches off main, merged with `--no-ff`. No direct commits to main.
- Verify behaviour before committing a feature (run it or test it).

## Hard rules (non-negotiable)

- Never commit secrets: `.env`, `*.tfvars`, `*.tfstate*`, `*-key.json`, credentials. Only
  the `.example` placeholders are tracked. gitleaks runs in pre-commit.
- No credentials in code. Read everything from environment variables.
- Do not bypass hooks with `--no-verify`.

## Read next

- `CLAUDE.md` for the full standards (Python, SQL and dbt, OpenTofu, data engineering).
- `docs/` for the architecture, the data model, a codebase tour, and the strategy engine.
- `README.md` for the project overview and how to run the stack.

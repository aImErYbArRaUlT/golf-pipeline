# Contributing

Thanks for your interest. This is a portfolio-shaped project, but issues and pull
requests are welcome.

## Getting set up

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and [just](https://github.com/casey/just).

```sh
just install      # sync runtime and dev dependencies
just hooks        # install the pre-commit hooks
just check        # lint, format check, and tests
```

The full stack (Docker, BigQuery, dbt, Airflow) is described in the README. Most code
changes only need the steps above.

## Development workflow

- Branch off `main`. Keep each pull request to one logical change.
- Use Conventional Commits: `type(scope): description` (types: feat, fix, docs, chore,
  refactor, test, ci).
- Run `just check` before you push. CI runs the same lint and tests.
- Add or update tests for behaviour you change. For the data models, the dbt tests are
  the data contract.

## Contributing data

The model is calibrated on tour averages and a few openly-posted exports, so real
launch-monitor data is the most valuable contribution of all (see the README's "Data gaps"
section for why). Full-bag sessions with many shots per club, from any monitor
(TrackMan, Foresight/Garmin, FlightScope, and others), help most. Send exports to
**aimery@barratec.com**, sharing only data you own or are free to pass on.

## Style

- Python is linted and formatted with ruff and black (line length 100).
- SQL is linted with sqlfluff (BigQuery dialect, lowercase keywords).
- These run in pre-commit, so a clean commit is already in style.

## Safety

- Never commit secrets (`.env`, `*.tfvars`, `*.tfstate*`, key files). Only the `.example`
  placeholders are tracked, and gitleaks runs in pre-commit. Do not bypass hooks.

See `AGENTS.md` if you are using an AI coding agent, and `CLAUDE.md` for the full project
standards.

"""Source registry.

Each launch monitor is one entry here. Adding a source on the ingestion side is
purely declarative: name it, say where its files are, and how to parse them
(encoding, units row). Column renaming and unit conversion are NOT done here -
that happens in the dbt staging layer, keeping bronze faithfully raw.

A source is either:
  * single-file - a direct CSV URL (`default_url`), or
  * multi-file - every file in a GitHub directory matching `path_pattern`,
    unioned into one bronze table. Real monitors export one file per session, so
    this is the production-shaped path (Garmin and FlightScope below use it).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    """Declarative description of one launch-monitor CSV source."""

    name: str
    url_env_var: str
    # Launch monitors put a units row ([mph], [deg], ...) on line 2, between the
    # header and the first data row. True => skip that row in every file.
    has_units_row: bool
    # utf-8-sig transparently strips a UTF-8 BOM (the Garmin export has one).
    encoding: str
    # Bronze table name in BigQuery (one table per source).
    bronze_table: str

    # ── single-file mode ──────────────────────────────────────
    default_url: str = ""  # used if the env var is unset

    # ── multi-file mode (GitHub directory) ────────────────────
    # Set both to ingest every file under a repo path and union them.
    github_repo: str = ""  # "owner/repo"
    github_branch: str = "main"
    path_pattern: str = ""  # regex over repo file paths, e.g. r"^Data/.*\.csv$"

    @property
    def url(self) -> str:
        """Resolved single-file URL: env var wins, else the documented default."""
        return os.environ.get(self.url_env_var, self.default_url)

    @property
    def is_multi_file(self) -> bool:
        return bool(self.github_repo and self.path_pattern)


# The researched, verified public datasets (see README "Data sources").
SOURCES: dict[str, Source] = {
    "trackman": Source(
        name="trackman",
        url_env_var="TRACKMAN_CSV_URL",
        has_units_row=True,
        encoding="utf-8",
        bronze_table="trackman_raw",
        default_url=(
            "https://raw.githubusercontent.com/tim-blackmore/"
            "launch-monitor-regression/main/data.csv"
        ),
    ),
    # Garmin Approach R10 - one CSV per range session. We ingest the whole Data/
    # directory (14 sessions) and union them. Session schemas vary (32 vs 42
    # columns), but every common-schema column is present in all of them, so the
    # schema-on-read union handles it. Different schema/units from TrackMan.
    "foresight": Source(
        name="foresight",
        url_env_var="FORESIGHT_CSV_URL",
        has_units_row=True,
        encoding="utf-8-sig",  # strips the BOM
        bronze_table="foresight_raw",
        github_repo="jgamblin/golf",
        github_branch="main",
        path_pattern=r"^Data/DrivingRange.*\.csv$",
    ),
    # CaddieSet (MIT, arXiv 2508.20491): a camera monitor + biomechanics set.
    # METRIC units (m/s, m), club codes (W1/I7), multiple golfers, each shot in
    # two camera views. Staging converts units, dedups views, synthesizes the
    # fields it lacks. No units row, no BOM, plain UTF-8.
    "caddieset": Source(
        name="caddieset",
        url_env_var="CADDIESET_CSV_URL",
        has_units_row=False,
        encoding="utf-8",
        bronze_table="caddieset_raw",
        default_url=("https://raw.githubusercontent.com/damilab/CaddieSet/main/data/CaddieSet.csv"),
    ),
    # FlightScope Mevo - a fourth monitor type (doppler). One CSV per club per
    # session under range/. Already imperial (no conversion). No units row; the
    # session date lives in the folder name, so staging parses it from lineage.
    "flightscope": Source(
        name="flightscope",
        url_env_var="FLIGHTSCOPE_CSV_URL",
        has_units_row=False,
        encoding="utf-8",
        bronze_table="flightscope_raw",
        github_repo="sghill/golf",
        github_branch="master",
        path_pattern=r"^range/.*\.csv$",
    ),
}


def get_source(name: str) -> Source:
    """Look up a source by name, with a helpful error listing valid names."""
    try:
        return SOURCES[name]
    except KeyError:
        valid = ", ".join(sorted(SOURCES))
        raise SystemExit(f"Unknown source '{name}'. Valid sources: {valid}") from None

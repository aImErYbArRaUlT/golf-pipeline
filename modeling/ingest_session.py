"""Ingest a personal launch-monitor session into the warehouse.

The CSV-upload path builds a bag live but doesn't persist; this lands a player's
own session in gold so it becomes a permanent **My ingested data** player. It is
the same medallion pipeline every source uses - it just reads a *local* file and
conforms it client-side:

    raw export CSV  ->  conform headers to the common schema (`players.conform_export`)
                    ->  stamp the player, land in MinIO + `<env>_bronze.manual_raw`
                    ->  `just dbt-run <env>`  ->  silver -> gold -> the app

The "manual" source is defined here (a local file, not a URL), so the URL-based
source registry is untouched. `stg_manual` types it the same way every staging
model does. Run via `just ingest-session <file> <player>`.
"""

from __future__ import annotations

import argparse
import csv
import io
import logging

from golf_ingest import storage, transform
from golf_ingest.config import BigQueryConfig, MinioConfig
from golf_ingest.loader import load_parquet
from golf_ingest.sources import Source

from .players import conform_export

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("ingest_session")

# A local-file source: no URL, no units row. parse_csv/assemble_bronze only read
# name/encoding/has_units_row, and we feed the file ourselves, so this is all it needs.
_MANUAL = Source(
    name="manual",
    url_env_var="",
    has_units_row=False,
    encoding="utf-8",
    bronze_table="manual_raw",
)

# The common-schema columns written to bronze (player first; lineage added downstream).
_COLUMNS = [
    "player",
    "club",
    "session_date",
    "ball_speed_mph",
    "club_speed_mph",
    "smash_factor",
    "launch_angle_deg",
    "spin_rate_rpm",
    "carry_yards",
    "total_yards",
    "side_dispersion",
    "spin_axis_deg",
    "launch_direction_deg",
]


def _conformed_csv(path: str, player: str) -> tuple[bytes, int, int]:
    """Read a raw export, conform its headers, stamp the player; return CSV bytes.

    Returns (bytes, n_rows, n_with_ball_speed) so the caller can report how much of
    the session is usable (rows without ball speed are dropped at silver)."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        raw_rows = list(csv.DictReader(f))
    rows = conform_export(raw_rows)
    usable = 0
    for r in rows:
        r["player"] = player  # the session's owner (the export rarely names them)
        if str(r.get("ball_speed_mph", "")).strip():
            usable += 1
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({c: r.get(c, "") for c in _COLUMNS})
    return buf.getvalue().encode("utf-8"), len(rows), usable


def ingest_session(path: str, player: str, *, load_to_bq: bool = True) -> None:
    """Conform a local session CSV and land it in `<env>_bronze.manual_raw`."""
    csv_bytes, n_rows, usable = _conformed_csv(path, player)
    log.info(
        "[manual] %s: %d rows (%d with launch data) for player %r", path, n_rows, usable, player
    )
    if usable == 0:
        raise SystemExit(
            "No rows have a ball-speed column the engine can use. Check the export's "
            "headers - see modeling/players.py `_HEADER_ALIASES` for what's recognised."
        )

    minio = MinioConfig.from_env()
    storage.put_object(minio, f"raw/manual/{player}.csv", csv_bytes)
    frame = transform.parse_csv(csv_bytes, _MANUAL, f"{player}.csv")
    df = transform.assemble_bronze([frame], _MANUAL)
    parquet = transform.frame_to_parquet(df)
    storage.put_object(minio, "parquet/manual/manual.parquet", parquet)
    log.info("[manual] landed %d rows in MinIO", len(df))

    if not load_to_bq:
        log.info("[manual] --no-load set; skipping BigQuery")
        return
    bq = BigQueryConfig.from_env()
    table_id = load_parquet(bq, parquet, _MANUAL.bronze_table)
    log.info("[manual] loaded -> %s (WRITE_TRUNCATE)", table_id)
    log.info("[manual] now run `just dbt-run %s` to flow it to gold.", bq.env)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a personal session CSV into bronze.")
    parser.add_argument(
        "--file", required=True, help="Path to the session CSV (any export format)."
    )
    parser.add_argument("--player", required=True, help="Player name to stamp on every shot.")
    parser.add_argument(
        "--no-load", action="store_true", help="Skip BigQuery (MinIO + Parquet only)."
    )
    args = parser.parse_args()
    ingest_session(args.file, args.player, load_to_bq=not args.no_load)


if __name__ == "__main__":
    main()

"""Phase 1 ingestion entrypoint.

End to end for one source:
    fetch CSV  ->  parse + sanitize  ->  Parquet
               ->  land raw CSV + Parquet in MinIO (bronze object store)
               ->  load Parquet into BigQuery bronze table

Run via the justfile: `just ingest trackman`. Use `--no-load` to run the
object-storage half without BigQuery (handy before GCP is configured).
"""

from __future__ import annotations

import argparse
import logging

from . import storage, transform
from .config import BigQueryConfig, MinioConfig
from .loader import load_parquet
from .sources import SOURCES, get_source

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("golf_ingest")


def ingest_source(name: str, *, load_to_bq: bool = True) -> None:
    """Run the full ingestion for a single named source (one or many files)."""
    source = get_source(name)
    minio = MinioConfig.from_env()

    specs = transform.resolve_file_specs(source)
    log.info("[%s] resolved %d file(s)", name, len(specs))

    # Fetch each file, land its raw bytes in MinIO, and collect the parsed frame.
    frames = []
    for label, url in specs:
        raw = transform.fetch_csv(url)
        storage.put_object(minio, f"raw/{name}/{label}", raw)
        frames.append(transform.parse_csv(raw, source, label))

    df = transform.assemble_bronze(frames, source)
    log.info("[%s] assembled %d rows x %d columns", name, len(df), df.shape[1])
    parquet = transform.frame_to_parquet(df)

    # The unioned bronze Parquet - a stable key, so re-runs overwrite in place.
    parquet_uri = storage.put_object(minio, f"parquet/{name}/{name}.parquet", parquet)
    log.info("[%s] landed parquet -> %s", name, parquet_uri)

    if not load_to_bq:
        log.info("[%s] --no-load set; skipping BigQuery", name)
        return

    bq = BigQueryConfig.from_env()
    table_id = load_parquet(bq, parquet, source.bronze_table)
    log.info("[%s] loaded -> %s (WRITE_TRUNCATE)", name, table_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a launch-monitor CSV into bronze.")
    parser.add_argument(
        "--source",
        default="trackman",
        choices=sorted(SOURCES),
        help="Which source to ingest (default: trackman).",
    )
    parser.add_argument(
        "--no-load",
        action="store_true",
        help="Skip the BigQuery load (fetch + Parquet + MinIO only).",
    )
    args = parser.parse_args()
    ingest_source(args.source, load_to_bq=not args.no_load)


if __name__ == "__main__":
    main()

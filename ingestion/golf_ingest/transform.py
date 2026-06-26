"""Fetch and transform raw CSV into bronze Parquet.

Bronze stays faithful to the source: we do NOT rename metrics or convert units
(that's the dbt staging layer's job). The only changes here are mechanical and
warehouse-driven:
  * skip the units row that launch monitors emit on line 2,
  * sanitize column names to snake_case (BigQuery rejects spaces/dots),
  * add lineage columns (source, source file, row index, ingest timestamp).

A source can be a single CSV or a whole GitHub directory of per-session files;
multi-file sources are fetched per file and unioned (schema-on-read, so files
with slightly different column sets combine cleanly). Parquet is the bronze
artifact - columnar, typed, compressed, and cheap to load into BigQuery.
"""

from __future__ import annotations

import io
import os
import re
import urllib.parse
from datetime import UTC, datetime

import pandas as pd
import requests

from .sources import Source

_REQUEST_TIMEOUT_SECONDS = 60


def fetch_csv(url: str) -> bytes:
    """Download a CSV. Raises on any non-200 response."""
    response = requests.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.content


def sanitize_column(name: str) -> str:
    """Make a raw header BigQuery-safe: snake_case, alnum + underscore only.

    Examples: 'Club Speed' -> 'club_speed', 'Dyn. Loft' -> 'dyn_loft',
    'Launch Angle V (°)' -> 'launch_angle_v'.
    """
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)  # non-alnum runs -> single _
    name = re.sub(r"_+", "_", name).strip("_")  # collapse + trim underscores
    return name or "unnamed"


def _list_github_files(repo: str, branch: str, pattern: str) -> list[tuple[str, str]]:
    """List a GitHub repo's files matching `pattern`, as (path, raw_url) pairs.

    One API call per source (the recursive git-tree). Uses GITHUB_TOKEN/GH_TOKEN
    if present to lift the unauthenticated 60/hour limit; unauthenticated is fine
    for a handful of sources.
    """
    api = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(api, headers=headers, timeout=_REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    rx = re.compile(pattern)
    specs = []
    for node in resp.json().get("tree", []):
        path = node.get("path", "")
        if node.get("type") == "blob" and rx.match(path):
            raw_url = (
                f"https://raw.githubusercontent.com/{repo}/{branch}/{urllib.parse.quote(path)}"
            )
            specs.append((path, raw_url))
    return sorted(specs)


def resolve_file_specs(source: Source) -> list[tuple[str, str]]:
    """Resolve a source to the list of (label, url) files to ingest."""
    if source.is_multi_file:
        return _list_github_files(source.github_repo, source.github_branch, source.path_pattern)
    url = source.url
    return [(url.rsplit("/", 1)[-1], url)]


def parse_csv(raw: bytes, source: Source, source_file: str) -> pd.DataFrame:
    """Parse one file's bytes into a frame: sanitized columns + a _source_file tag.

    Everything lands as strings; typing and unit conversion happen in staging.
    """
    skiprows = [1] if source.has_units_row else None
    df = pd.read_csv(
        io.BytesIO(raw),
        encoding=source.encoding,
        skiprows=skiprows,
        dtype=str,  # land everything as strings
        keep_default_na=False,  # preserve raw empties verbatim within a file
    )
    df.columns = [sanitize_column(c) for c in df.columns]
    df.insert(0, "_source_file", source_file)
    return df


def assemble_bronze(frames: list[pd.DataFrame], source: Source) -> pd.DataFrame:
    """Union per-file frames into one bronze frame with lineage.

    Files with different column sets combine via an outer union (missing cells
    become null). A global _row_index gives each shot a deterministic identity
    that staging hashes into shot_id - so re-ingesting yields the same ids.
    """
    if len(frames) == 1:
        df = frames[0].copy()
    else:
        df = pd.concat(frames, ignore_index=True, sort=False)
    df.insert(0, "_source", source.name)
    df.insert(2, "_row_index", range(len(df)))  # after _source, _source_file
    df["_ingested_at_utc"] = datetime.now(UTC).isoformat()
    return df


def frame_to_parquet(df: pd.DataFrame) -> bytes:
    """Serialize a DataFrame to Parquet bytes (snappy-compressed)."""
    buffer = io.BytesIO()
    df.to_parquet(buffer, engine="pyarrow", compression="snappy", index=False)
    return buffer.getvalue()

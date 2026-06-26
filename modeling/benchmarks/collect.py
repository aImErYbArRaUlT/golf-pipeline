"""Disposable collector for public benchmark tables - NOT part of the pipeline.

It only fetches and parses **HTML tables**, writing raw CSVs next to this file
(`<name>.raw.csv`) for you to review, clean, and commit. Nothing is executed; it
just reads pages and writes CSVs.

    just collect-benchmarks <url> [table_index]   # ad-hoc: scrape one HTML table
    just collect-benchmarks                        # run the registered SOURCES

The genuinely useful benchmarks so far (TrackMan's averages graphic, Broadie's
paper) are PDF/image tables, not machine-readable - those numbers were
transcribed with a vision pass and verified by hand (see SOURCES.md). This tool
covers the easy half: any site that publishes a plain `<table>`.

Needs `pandas` + `lxml` (the `collect` dependency group).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# (name, url, table_index_on_page, note) - register stable HTML-table sources here.
SOURCES: list[tuple[str, str, int, str]] = []


def _grab(name: str, url: str, index: int, note: str, out_dir: Path) -> None:
    try:
        df = pd.read_html(url)[index]
    except Exception as exc:  # network, parser, or no such table - all non-fatal
        print(f"{name}: FAILED ({type(exc).__name__}: {exc}); transcribe by hand - see SOURCES.md")
        return
    path = out_dir / f"{name}.raw.csv"
    df.to_csv(path, index=False)
    print(f"{name}: wrote {path.name} ({len(df)} rows; {note}) - review before committing")


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    out_dir = Path(__file__).parent

    if argv:
        url = argv[0]
        index = int(argv[1]) if len(argv) > 1 else 0
        jobs = [("adhoc", url, index, "from CLI")]
    else:
        jobs = SOURCES

    if not jobs:
        print("usage: collect <url> [table_index]   (or register SOURCES in collect.py)")
        print("PDF/image tables (TrackMan, Broadie) need a vision pass; see SOURCES.md.")
        return

    for name, url, index, note in jobs:
        _grab(name, url, index, note, out_dir)


if __name__ == "__main__":
    main()

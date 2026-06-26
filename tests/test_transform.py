"""Unit tests for bronze transform logic (no network, no warehouse)."""

from __future__ import annotations

from golf_ingest.sources import Source
from golf_ingest.transform import assemble_bronze, parse_csv, sanitize_column

# A throwaway source mirroring the TrackMan parse rules (units row on line 2).
_SOURCE = Source(
    name="testmon",
    url_env_var="X",
    has_units_row=True,
    encoding="utf-8",
    bronze_table="testmon_raw",
    default_url="http://example/x.csv",
)


def test_sanitize_column_handles_launch_monitor_headers():
    assert sanitize_column("Club Speed") == "club_speed"
    assert sanitize_column("Dyn. Loft") == "dyn_loft"
    assert sanitize_column("Max Height - Dist.") == "max_height_dist"
    assert sanitize_column("Launch Angle V (°)") == "launch_angle_v"
    assert sanitize_column("  Spin Rate  ") == "spin_rate"


def test_parse_csv_skips_units_row_and_tags_source_file():
    raw = (
        b"Club,Ball Speed,Spin Rate\n"
        b",[mph],[rpm]\n"  # units row -> must be dropped
        b"Driver,127.5,1760\n"
        b"Driver,130.2,1810\n"
    )
    df = parse_csv(raw, _SOURCE, "session_a.csv")

    # Units row gone -> two data rows; columns sanitized; lineage tag present.
    assert len(df) == 2
    assert list(df.columns) == ["_source_file", "club", "ball_speed", "spin_rate"]
    assert (df["_source_file"] == "session_a.csv").all()
    assert df.iloc[0]["ball_speed"] == "127.5"


def test_assemble_bronze_unions_heterogeneous_files():
    # Two "sessions" with different column sets - the real Garmin situation.
    # (Each has the line-2 units row _SOURCE expects.)
    a = parse_csv(b"Club,Ball Speed,Note\n,,\nDriver,150,x\n", _SOURCE, "a.csv")
    b = parse_csv(b"Club,Ball Speed\n,\n7 Iron,120\n", _SOURCE, "b.csv")

    df = assemble_bronze([a, b], _SOURCE)

    # Both rows survive; the column union covers all files (Note only in a.csv).
    assert len(df) == 2
    expected = {"_source", "_source_file", "_row_index", "club", "ball_speed", "note"}
    assert expected <= set(df.columns)
    # Lineage: source set, row index is a global 0-based sequence.
    assert (df["_source"] == "testmon").all()
    assert list(df["_row_index"]) == [0, 1]
    # The missing 'note' cell in b.csv's row is null, not a crash.
    assert df.loc[df["_source_file"] == "b.csv", "note"].isna().all()

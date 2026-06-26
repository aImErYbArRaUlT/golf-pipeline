"""The personal-session ingest: conform headers + stamp the player before bronze."""

from __future__ import annotations

import csv
import io

from modeling.ingest_session import _COLUMNS, _conformed_csv


def test_conformed_csv_maps_stamps_and_counts(tmp_path) -> None:
    # A raw export: spaced headers, an unrecognised column, and one row with no ball
    # speed (a non-shot). Conform maps the headers, stamps the player on every row,
    # and reports how many rows carry the launch data the engine needs.
    lines = ["Club,Ball Speed,Launch Angle,Spin Rate,Carry,Junk"]
    lines += [f"7 Iron,{120 + i % 3},17,6500,165,x" for i in range(5)]
    lines += ["Sand Wedge,,30,9000,90,x"]  # missing ball speed -> not usable
    path = tmp_path / "session.csv"
    path.write_text("\n".join(lines))

    data, n_rows, usable = _conformed_csv(str(path), "Tester")
    assert n_rows == 6
    assert usable == 5  # the empty-ball-speed row is dropped downstream

    out = list(csv.DictReader(io.StringIO(data.decode())))
    assert set(out[0]) == set(_COLUMNS)  # only the common-schema columns, "Junk" gone
    assert all(r["player"] == "Tester" for r in out)  # player stamped on every row
    assert out[0]["ball_speed_mph"] == "120"  # header conformed, value carried through

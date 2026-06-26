"""Player profiles - same engine, different people (different distances)."""

from __future__ import annotations

import math
import os

import pytest

from modeling.players import (
    PROFILES,
    bag_from_shots,
    bag_from_warehouse,
    conform_export,
    load_player_csv,
    profile_bag,
    profile_tour_clubs,
)


def test_conform_export_maps_raw_headers() -> None:
    # A raw export: spaced/cased headers, units in brackets, an extra column.
    rows = [
        {
            "Club": "7 Iron",
            "Ball Speed [mph]": "115",
            "Launch Angle": "17",
            "Spin Rate": "6500",
            "Carry": "158",
            "Note": "good",
        }
    ]
    out = conform_export(rows)
    assert out[0] == {
        "club": "7 Iron",
        "ball_speed_mph": "115",
        "launch_angle_deg": "17",
        "spin_rate_rpm": "6500",
        "carry_yards": "158",
    }  # recognised columns renamed, "Note" dropped


def test_conform_export_passes_through_common_schema() -> None:
    row = {"club": "Driver", "ball_speed_mph": "150", "spin_rate_rpm": "2700"}
    assert conform_export([row])[0] == row  # already-conformed is unchanged


def test_raw_export_uploads_into_a_bag() -> None:
    # The whole upload path on a raw export: headers conformed, then a bag built.
    header = "Club,Ball Speed,Launch Angle,Spin Rate,Carry,Smash"
    lines = [header]
    lines += [f"7 Iron,{115 + i % 3},17,6500,{158 + i % 4},1.38" for i in range(12)]
    lines += [f"Driver,{150 + i % 3},12,2700,{250 + i % 5},1.49" for i in range(12)]
    bag, real = load_player_csv("\n".join(lines))
    assert real == {"7-iron", "Driver"}  # both clubs measured from the raw export
    driver = next(c for c in bag.clubs if c.dispersion.club == "Driver")
    assert 240 < driver.measured_carry_mean < 256  # anchored to the export's carry


def _driver_carry(bag) -> float:
    return next(c.dispersion.carry_mean_yards for c in bag.clubs if c.dispersion.club == "Driver")


def _driver(clubs):
    return next(c for c in clubs if c.club == "Driver")


def test_profiles_scale_distance() -> None:
    pro = profile_bag("PGA tour pro")
    senior = profile_bag("Senior")
    assert _driver_carry(pro) > 270  # tour driver ~282
    assert _driver_carry(senior) < 230  # a senior carries it much shorter
    assert _driver_carry(pro) - _driver_carry(senior) > 40  # genuinely different players


def test_profile_stock_clubs_scaled() -> None:
    # The conditions adjuster flies these; a slower player must get slower stock shots.
    pro = profile_tour_clubs("PGA tour pro")
    senior = profile_tour_clubs("Senior")
    assert _driver(senior).ball_speed_mph < _driver(pro).ball_speed_mph - 30
    assert _driver(senior).carry_yards < _driver(pro).carry_yards - 40


def test_registry_covers_the_expected_players() -> None:
    assert {"PGA tour pro", "Senior", "LPGA tour"} <= set(PROFILES)


def _shots(club, ball, launch, spin, n=12):
    return [
        {
            "club": club,
            "ball_speed_mph": ball + math.sin(i) * 0.5,
            "launch_angle_deg": launch + math.cos(i) * 0.5,
            "spin_rate_rpm": spin + i * 5,
        }
        for i in range(n)
    ]


def test_bag_from_real_shots_measures_and_gap_fills() -> None:
    # A partial export - Driver, "7 iron", "pw" (variant labels) - builds a full bag:
    # those clubs measured from the data, the rest inferred and flagged.
    rows = _shots("Driver", 150, 12, 2700) + _shots("7 iron", 110, 17, 6200)
    rows += _shots("pw", 82, 24, 9000)
    bag, real = bag_from_shots(rows, player="Tester")
    assert real == {"Driver", "7-iron", "PW"}  # labels normalised, all recognised
    assert {c.dispersion.club for c in bag.clubs} >= {"Driver", "7-iron", "PW", "5-iron"}
    driver = next(c for c in bag.clubs if c.dispersion.club == "Driver")
    assert 230 < driver.measured_carry_mean < 255  # ~150 mph ball speed
    assert bag.clubs[0].dispersion.carry_mean_yards >= bag.clubs[-1].dispersion.carry_mean_yards


def _shots_with_carry(club, ball, launch, spin, carry, n=12):
    rows = _shots(club, ball, launch, spin, n)
    for i, r in enumerate(rows):
        r["carry_yards"] = carry + math.sin(i) * 1.0
    return rows


def test_real_bag_anchors_distance_to_measured_carry() -> None:
    # The shots carry a fast ball speed (the engine would simulate a long carry) but
    # the monitor reports 140 yds. The caddie must report the player's *measured*
    # distance, so the club's cloud is recentred on 140, not the simulated figure.
    rows = _shots_with_carry("7 iron", 130, 17, 6200, 140)
    bag, real = bag_from_shots(rows, player="Tester")
    seven = next(c for c in bag.clubs if c.dispersion.club == "7-iron")
    assert "7-iron" in real
    assert abs(seven.measured_carry_mean - 140) < 2  # anchored to measured
    assert abs(seven.dispersion.carry_mean_yards - 140) < 2  # cloud recentred there


def test_gross_mishits_are_dropped() -> None:
    # Twelve real 7-irons plus four whiffs (a fifth of the ball speed). The whiffs must
    # be trimmed, so the dispersion is fit on the 12 strikes and the distance holds.
    good = _shots_with_carry("7 iron", 115, 17, 6200, 150, n=12)
    whiffs = [
        {"club": "7 iron", "ball_speed_mph": 35, "launch_angle_deg": 40, "spin_rate_rpm": 1000}
        for _ in range(4)
    ]
    bag, _ = bag_from_shots(good + whiffs, player="Tester")
    seven = next(c for c in bag.clubs if c.dispersion.club == "7-iron")
    assert seven.dispersion.n_observed == 12  # the four whiffs trimmed before the fit
    assert abs(seven.measured_carry_mean - 150) < 3  # and they didn't drag the distance


def test_bag_from_warehouse_builds_a_real_anchored_bag() -> None:
    # Integration: the warehouse path is the same accurate builder on ingested gold
    # shots. Skips cleanly when BigQuery isn't configured (CI without credentials).
    if not os.environ.get("GCP_PROJECT_ID"):
        pytest.skip("no warehouse configured (GCP_PROJECT_ID unset)")
    try:
        from modeling import warehouse

        bq = warehouse.client()
        players = warehouse.list_player_bags(bq)
    except Exception as e:  # noqa: BLE001 - any auth/connection failure → skip
        pytest.skip(f"warehouse unavailable: {e}")
    real_players = [p for p in players if p["source"] != "trackman"]  # trackman = tour avg
    if not real_players:
        pytest.skip("no ingested per-player launch data")
    p = real_players[0]
    bag, real = bag_from_warehouse(bq, p["source"], p["player"])
    assert real  # at least one club built from the player's real shots
    for cs in bag.clubs:  # real clubs' clouds are anchored to their measured carries
        if cs.dispersion.club in real:
            assert abs(cs.dispersion.carry_mean_yards - cs.measured_carry_mean) < 1.5

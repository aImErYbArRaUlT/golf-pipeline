"""Benchmark-data tests - the cited CSV loads, maps units, and feeds the engine.

No warehouse: just the reference data, the contract mapping, and a sanity flight.
"""

from __future__ import annotations

import math

import pytest

from modeling.benchmarks import load_trackman_lpga, load_trackman_pga
from modeling.calibration import calibrate
from modeling.contracts import MPH_TO_MS, RPM_TO_RAD_S
from modeling.physics import simulate


def test_loads_full_bag_descending():
    clubs = load_trackman_pga()
    assert len(clubs) == 12
    assert clubs[0].club == "Driver"
    assert clubs[-1].club == "PW"
    carries = [c.carry_yards for c in clubs]
    assert carries == sorted(carries, reverse=True)  # driver longest, wedge shortest
    assert carries[0] == 282  # TrackMan 2024 PGA driver carry


def test_to_shot_input_converts_units():
    driver = load_trackman_pga()[0]
    si = driver.to_shot_input()
    assert si.ball_speed_ms == pytest.approx(171 * MPH_TO_MS)
    assert si.launch_angle_rad == pytest.approx(math.radians(10.4))
    assert si.spin_rate_rad_s == pytest.approx(2545 * RPM_TO_RAD_S)
    assert si.measured_carry_yards == 282
    assert si.club == "Driver"


def test_engine_flies_the_driver_in_a_tour_plausible_band():
    carry = simulate(load_trackman_pga()[0].to_shot_input()).carry_yards
    assert 230 < carry < 320


def test_lpga_bag_loads():
    clubs = load_trackman_lpga()
    assert len(clubs) == 11  # has a hybrid, no 3-iron
    assert clubs[0].club == "Driver"
    assert clubs[-1].club == "PW"
    carries = [c.carry_yards for c in clubs]
    assert carries == sorted(carries, reverse=True)
    assert carries[0] == 223


def test_one_aero_model_fits_the_lpga_bag_too():
    # Calibrating the same engine on the women's tour also lands a tight fit -
    # the spin-drag model isn't tuned to one swing speed.
    result = calibrate([c.to_shot_input() for c in load_trackman_lpga()])
    assert result.mae_after_yards < 8.0

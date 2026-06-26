"""Physics engine behaviour tests (no warehouse needed).

These assert the trajectory responds correctly to inputs - the Stage A
acceptance criteria - using relative comparisons that don't depend on the exact
calibrated coefficients.
"""

from __future__ import annotations

import math

import pytest

from modeling.contracts import MPH_TO_MS, RPM_TO_RAD_S, ShotInput
from modeling.physics import simulate


def _driver(
    spin_rpm: float = 2700,
    axis_deg: float = 0.0,
    air_density: float = 1.225,
    launch_deg: float = 12.0,
    ball_mph: float = 150.0,
) -> ShotInput:
    return ShotInput(
        ball_speed_ms=ball_mph * MPH_TO_MS,
        launch_angle_rad=math.radians(launch_deg),
        launch_direction_rad=0.0,
        spin_rate_rad_s=spin_rpm * RPM_TO_RAD_S,
        spin_axis_rad=math.radians(axis_deg),
        air_density=air_density,
    )


def test_driver_carry_is_physically_sensible():
    t = simulate(_driver())
    assert 150 < t.carry_yards < 330  # a driver, not a wedge or a moon shot
    assert t.peak_height_yards > 0
    assert t.descent_angle_deg > 0  # comes down, not up


def test_more_backspin_flies_higher():
    low = simulate(_driver(spin_rpm=2000))
    high = simulate(_driver(spin_rpm=3500))
    assert high.peak_height_yards > low.peak_height_yards


def test_spin_axis_sign_sets_curve_direction():
    fade = simulate(_driver(axis_deg=8))  # + axis -> fade (right) for a RH golfer
    draw = simulate(_driver(axis_deg=-8))
    straight = simulate(_driver(axis_deg=0))
    assert fade.lateral_yards > 1
    assert draw.lateral_yards < -1
    assert abs(straight.lateral_yards) < 1


def test_thinner_air_carries_farther():
    sea = simulate(_driver(air_density=1.225))
    altitude = simulate(_driver(air_density=1.0))  # ~2,000 m elevation
    assert altitude.carry_yards > sea.carry_yards


def test_roll_releases_low_spin_and_checks_high_spin():
    driver = simulate(_driver(spin_rpm=2500))
    wedge = simulate(_driver(spin_rpm=9000, ball_mph=95, launch_deg=24))
    driver_roll = driver.total_yards - driver.carry_yards
    wedge_roll = wedge.total_yards - wedge.carry_yards
    assert driver.total_yards > driver.carry_yards  # a driver releases and runs
    assert driver_roll > wedge_roll  # high backspin checks the ball
    assert wedge.total_yards == pytest.approx(wedge.carry_yards, abs=5)


def test_wind_pushes_the_ball():
    from modeling.conditions import wind_vector

    calm = simulate(_driver()).carry_yards
    head = simulate(_driver(), wind=wind_vector(15, 0)).carry_yards
    tail = simulate(_driver(), wind=wind_vector(15, 180)).carry_yards
    cross = simulate(_driver(), wind=wind_vector(15, 90))  # from the right
    assert head < calm < tail  # headwind shortens, tailwind lengthens
    assert cross.lateral_yards < -1  # a right wind pushes the ball left


def test_lift_saturates_at_high_spin():
    # Past the physical Cl ceiling, piling on spin adds no more lift, so an
    # iron-like high-spin shot descends steeply instead of floating, and extra
    # spin beyond the cap leaves the flight unchanged.
    iron = _driver(spin_rpm=8000, ball_mph=115, launch_deg=18)
    hotter = _driver(spin_rpm=12000, ball_mph=115, launch_deg=18)
    assert simulate(iron).descent_angle_deg > 15  # comes down like an iron, no glide
    assert simulate(hotter).carry_yards == pytest.approx(simulate(iron).carry_yards, abs=1.0)


def test_landing_height_shifts_carry():
    # Uphill ground (target above the launch) catches the ball earlier, so it
    # carries shorter; downhill, later, so it carries longer. Flat is the default.
    flat = simulate(_driver()).carry_yards
    uphill = simulate(_driver(), landing_height=5.0).carry_yards  # green 5 m above
    downhill = simulate(_driver(), landing_height=-5.0).carry_yards
    assert uphill < flat < downhill
    assert abs((flat - uphill) - (downhill - flat)) < 1.0  # roughly symmetric

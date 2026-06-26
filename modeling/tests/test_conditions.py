"""Conditions tests - air density, the wind vector convention, the bag adjuster."""

from __future__ import annotations

import pytest

from modeling.benchmarks import load_trackman_pga
from modeling.conditions import (
    adjust_bag_for_conditions,
    air_density,
    relative_wind,
    wind_vector,
)
from modeling.synthetic import TOUR, synthetic_bag


def test_sea_level_standard_density():
    assert air_density(15.0, 0.0) == pytest.approx(1.225, abs=0.005)


def test_hot_and_high_air_is_thinner():
    sea = air_density(15.0, 0.0)
    assert air_density(30.0, 0.0) < sea  # hotter = thinner
    assert air_density(15.0, 2000.0) < sea  # higher = thinner


def test_wind_vector_directions():
    # x downrange, y lateral (+right). from_deg = where the wind comes from.
    head = wind_vector(10.0, 0.0)
    tail = wind_vector(10.0, 180.0)
    from_right = wind_vector(10.0, 90.0)
    assert head[0] < 0 and abs(head[1]) < 1e-9  # headwind blows -x
    assert tail[0] > 0 and abs(tail[1]) < 1e-9  # tailwind blows +x
    assert from_right[1] < 0 and abs(from_right[0]) < 1e-9  # right wind pushes left


def test_relative_wind_depends_on_hole_bearing():
    # A fixed compass wind from the South (180): a hole you play due south faces
    # into it (headwind, -x); a hole you play due north is downwind (+x).
    into = relative_wind(10.0, 180.0, 180.0)
    down = relative_wind(10.0, 180.0, 0.0)
    cross = relative_wind(10.0, 180.0, 90.0)  # play east, south wind off the right
    assert into[0] < 0 and abs(into[1]) < 1e-9
    assert down[0] > 0 and abs(down[1]) < 1e-9
    assert cross[1] < 0 and abs(cross[0]) < 1e-9


def _carry(bag, club):
    return next(c.dispersion.carry_mean_yards for c in bag.clubs if c.dispersion.club == club)


def _lateral(bag, club):
    return next(c.dispersion.lateral_mean_yards for c in bag.clubs if c.dispersion.club == club)


def _driver_std(bag):
    return next(c.dispersion.carry_std_yards for c in bag.clubs if c.dispersion.club == "Driver")


def test_calm_at_sea_level_is_a_noop():
    bag = synthetic_bag("pga", TOUR)
    same = adjust_bag_for_conditions(bag, load_trackman_pga(), wind=wind_vector(0, 0))
    assert same is bag  # nothing to do, returns the input untouched


def test_head_and_tail_wind_shift_carry():
    bag = synthetic_bag("pga", TOUR)
    clubs = load_trackman_pga()
    calm = _carry(bag, "Driver")
    head = adjust_bag_for_conditions(bag, clubs, wind=wind_vector(20, 0))
    tail = adjust_bag_for_conditions(bag, clubs, wind=wind_vector(20, 180))
    assert _carry(head, "Driver") < calm - 10  # headwind shortens
    assert _carry(tail, "Driver") > calm + 10  # tailwind lengthens
    # The cloud is translated, not re-dispersed: spread is unchanged.
    assert _driver_std(head) == pytest.approx(_driver_std(bag), abs=1e-6)


def test_crosswind_shifts_lateral_and_altitude_lengthens():
    bag = synthetic_bag("pga", TOUR)
    clubs = load_trackman_pga()
    from_right = adjust_bag_for_conditions(bag, clubs, wind=wind_vector(20, 90))
    assert _lateral(from_right, "Driver") < _lateral(bag, "Driver") - 5  # pushed left
    high = adjust_bag_for_conditions(bag, clubs, density=air_density(15, 2000))
    assert _carry(high, "Driver") > _carry(bag, "Driver") + 10  # thin air carries

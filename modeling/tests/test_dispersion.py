"""Dispersion behaviour - purely synthetic, no warehouse.

Builds clubs with controlled launch-condition spread and checks the Monte-Carlo
dispersion responds the way physics demands: no input variance -> no scatter,
more launch variance -> a bigger landing oval, and the result is reproducible
under a fixed seed.
"""

from __future__ import annotations

import math

import pytest

from modeling.contracts import MPH_TO_MS, RPM_TO_RAD_S, ShotInput
from modeling.dispersion import MIN_SHOTS, simulate_dispersion


def _shot(ball_mph: float, launch_deg: float, spin_rpm: float, dir_deg=0.0, axis_deg=0.0):
    return ShotInput(
        ball_speed_ms=ball_mph * MPH_TO_MS,
        launch_angle_rad=math.radians(launch_deg),
        launch_direction_rad=math.radians(dir_deg),
        spin_rate_rad_s=spin_rpm * RPM_TO_RAD_S,
        spin_axis_rad=math.radians(axis_deg),
    )


def _disperse(shots, seed=0):
    return simulate_dispersion(shots, source="t", player="p", club="7i", n_samples=500, seed=seed)


def test_no_input_variance_gives_no_scatter():
    shots = [_shot(150, 13, 2800)] * MIN_SHOTS
    d = _disperse(shots)
    assert d.carry_std_yards < 0.5
    assert d.lateral_std_yards < 0.5
    assert d.ellipse_semi_major_yards < 0.5


def test_more_spin_variance_widens_carry_spread():
    tight = [_shot(150, 13, 2800 + i * 5) for i in range(-6, 6)]
    loose = [_shot(150, 13, 2800 + i * 80) for i in range(-6, 6)]
    assert _disperse(loose).carry_std_yards > _disperse(tight).carry_std_yards


def test_direction_variance_widens_lateral_spread():
    straight = [_shot(150, 13, 2800, dir_deg=i * 0.1) for i in range(-6, 6)]
    sprayed = [_shot(150, 13, 2800, dir_deg=i * 1.5) for i in range(-6, 6)]
    assert _disperse(sprayed).lateral_std_yards > _disperse(straight).lateral_std_yards


def test_ellipse_major_at_least_minor():
    shots = [_shot(150, 13, 2800 + i * 60, dir_deg=i * 0.8) for i in range(-6, 6)]
    d = _disperse(shots)
    assert d.ellipse_semi_major_yards >= d.ellipse_semi_minor_yards


def test_seed_makes_it_reproducible():
    shots = [_shot(150, 13, 2800 + i * 60) for i in range(-6, 6)]
    assert _disperse(shots, seed=7).carry_mean_yards == _disperse(shots, seed=7).carry_mean_yards


def test_needs_enough_shots():
    with pytest.raises(ValueError, match="dispersion"):
        _disperse([_shot(150, 13, 2800)] * (MIN_SHOTS - 1))

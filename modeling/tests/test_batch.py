"""The vectorised batch integrator must agree with the single-shot reference.

`simulate_batch` is a fixed-step RK4 written for Monte-Carlo throughput;
`simulate` is the adaptive-step reference used for calibration. If they disagree,
dispersion would be flying a different physics than calibration validated - so
this is the load-bearing cross-check for Stage B.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from modeling.contracts import MPH_TO_MS, RPM_TO_RAD_S, ShotInput
from modeling.physics import simulate, simulate_batch


def _shot(ball_mph: float, launch_deg: float, spin_rpm: float, dir_deg=0.0, axis_deg=0.0):
    return ShotInput(
        ball_speed_ms=ball_mph * MPH_TO_MS,
        launch_angle_rad=math.radians(launch_deg),
        launch_direction_rad=math.radians(dir_deg),
        spin_rate_rad_s=spin_rpm * RPM_TO_RAD_S,
        spin_axis_rad=math.radians(axis_deg),
    )


# A spread that exercises straight, fading, drawing, high and low shots.
_SHOTS = [
    _shot(165, 11, 2600),
    _shot(150, 14, 3000, dir_deg=-2.0, axis_deg=6.0),  # push-fade
    _shot(120, 20, 5500, dir_deg=3.0, axis_deg=-8.0),  # high draw, iron-ish
    _shot(140, 9, 3500, axis_deg=2.0),
]


def test_batch_matches_single_shot_reference():
    # Non-default coefficients + wind exercise the lift cap, spin-drag and the
    # air-relative velocity in both paths.
    cd, cl, cd_spin = 0.25, 2.4, 0.2
    wind = np.array([-4.0, 2.0, 0.0])
    batch = simulate_batch(_SHOTS, cd, cl, cd_spin, wind=wind)
    for i, shot in enumerate(_SHOTS):
        ref = simulate(shot, cd, cl, cd_spin, wind=wind)
        assert batch.carry_yards[i] == pytest.approx(ref.carry_yards, abs=0.7)
        assert batch.total_yards[i] == pytest.approx(ref.total_yards, abs=0.8)
        assert batch.lateral_yards[i] == pytest.approx(ref.lateral_yards, abs=0.5)
        assert batch.peak_height_yards[i] == pytest.approx(ref.peak_height_yards, abs=0.7)
        assert batch.descent_angle_deg[i] == pytest.approx(ref.descent_angle_deg, abs=1.0)


def test_batch_preserves_order_and_shape():
    batch = simulate_batch(_SHOTS)
    assert batch.carry_yards.shape == (len(_SHOTS),)
    # the 165 mph driver carries farther than the 120 mph iron
    assert batch.carry_yards[0] > batch.carry_yards[2]


def test_empty_batch_returns_empty_arrays():
    batch = simulate_batch([])
    assert batch.carry_yards.shape == (0,)
    assert np.all(~np.isnan(batch.carry_yards))  # vacuously true, no shots

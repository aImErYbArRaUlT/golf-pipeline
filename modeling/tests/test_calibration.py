"""Calibration tests - self-consistency, no warehouse needed.

Generate synthetic "measured" carries by simulating a bag-spanning spread at known
coefficients, then check the calibrator recovers all three (drag, lift, spin-drag)
and drives the carry error to near zero. The spread of spin ratios is what makes
the spin-drag term identifiable.
"""

from __future__ import annotations

import math

import pytest

from modeling.calibration import calibrate, mean_abs_carry_error
from modeling.contracts import MPH_TO_MS, RPM_TO_RAD_S, ShotInput
from modeling.physics import simulate

_TRUE_CD = 0.25
_TRUE_CL = 2.3
_TRUE_CD_SPIN = 0.20


def _shots_with_synthetic_measured_carry() -> list[ShotInput]:
    """A driver-through-wedge spread, labelled with the carry the engine produces
    at the known coefficients."""
    shots = []
    for ball in (170, 150, 130, 110, 95):
        for launch in (10, 14, 20):
            for spin in (2600, 5000, 8000):
                base = ShotInput(
                    ball_speed_ms=ball * MPH_TO_MS,
                    launch_angle_rad=math.radians(launch),
                    launch_direction_rad=0.0,
                    spin_rate_rad_s=spin * RPM_TO_RAD_S,
                    spin_axis_rad=0.0,
                )
                carry = simulate(base, _TRUE_CD, _TRUE_CL, _TRUE_CD_SPIN).carry_yards
                shots.append(
                    ShotInput(
                        ball_speed_ms=base.ball_speed_ms,
                        launch_angle_rad=base.launch_angle_rad,
                        launch_direction_rad=0.0,
                        spin_rate_rad_s=base.spin_rate_rad_s,
                        spin_axis_rad=0.0,
                        measured_carry_yards=carry,
                    )
                )
    return shots


def test_calibration_recovers_known_coefficients_and_cuts_error():
    result = calibrate(_shots_with_synthetic_measured_carry())
    assert result.cd == pytest.approx(_TRUE_CD, abs=0.02)
    assert result.cl == pytest.approx(_TRUE_CL, abs=0.3)
    assert result.cd_spin == pytest.approx(_TRUE_CD_SPIN, abs=0.05)
    assert result.mae_after_yards < 1.5
    assert result.mae_after_yards <= result.mae_before_yards


def test_mean_abs_carry_error_is_zero_at_true_coefficients():
    shots = _shots_with_synthetic_measured_carry()
    assert mean_abs_carry_error(shots, _TRUE_CD, _TRUE_CL, _TRUE_CD_SPIN) < 1e-6


def test_calibrate_needs_enough_measured_shots():
    with pytest.raises(ValueError, match="measured-carry"):
        calibrate([])

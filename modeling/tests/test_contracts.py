"""Tests for the input contract + fct_shots mapper (no warehouse needed)."""

from __future__ import annotations

import math

from modeling.contracts import MPH_TO_MS, from_fct_row


def test_from_fct_row_converts_units_to_si():
    shot = from_fct_row(
        {
            "ball_speed_mph": 150.0,
            "launch_angle_deg": 12.0,
            "spin_rate_rpm": 2700.0,
            "spin_axis_deg": -4.0,
            "launch_direction_deg": 1.5,
            "source": "trackman",
            "club": "Driver",
            "carry_yards": 260.0,
        }
    )
    assert shot is not None
    assert math.isclose(shot.ball_speed_ms, 150.0 * MPH_TO_MS)
    assert math.isclose(shot.launch_angle_rad, math.radians(12.0))
    assert math.isclose(shot.spin_axis_rad, math.radians(-4.0))
    assert shot.measured_carry_yards == 260.0
    assert shot.club == "Driver"


def test_from_fct_row_requires_core_fields():
    # Missing spin -> can't simulate -> None (caller filters it out).
    assert from_fct_row({"ball_speed_mph": 150.0, "launch_angle_deg": 12.0}) is None


def test_from_fct_row_defaults_missing_shape_fields_to_zero():
    # FlightScope has no spin axis / launch direction; they default to 0.
    shot = from_fct_row(
        {"ball_speed_mph": 110.0, "launch_angle_deg": 14.0, "spin_rate_rpm": 3000.0}
    )
    assert shot is not None
    assert shot.spin_axis_rad == 0.0
    assert shot.launch_direction_rad == 0.0

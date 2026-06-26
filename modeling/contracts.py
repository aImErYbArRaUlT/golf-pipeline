"""Input contract for the modeling core (Stage A).

The physics engine reads a documented contract - not the raw warehouse schema.
Four monitor schemas flow into `fct_shots` and the schema has already changed
once; a contract plus a thin mapper means the physics core never changes when a
source is added or renamed - only the mapper does.

Everything in `ShotInput` is SI (m/s, radians, rev/s). The mapper does the unit
conversion from the gold schema's mph / degrees / rpm / yards.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ── unit conversions ──────────────────────────────────────────
MPH_TO_MS = 0.44704
YARDS_TO_M = 0.9144
M_TO_YARDS = 1.0 / YARDS_TO_M
RPM_TO_RAD_S = 2.0 * math.pi / 60.0

# Standard atmosphere (sea level, 15 °C) - the default environment.
RHO_SEA_LEVEL = 1.225  # kg/m^3


@dataclass(frozen=True)
class ShotInput:
    """One shot's launch conditions in SI units, ready for the integrator.

    Angles: launch_angle is elevation (rad); launch_direction is azimuth (rad,
    + = right of target); spin_axis is the spin-axis tilt (rad, + = fade for a
    right-handed golfer). air_density defaults to standard sea level.
    """

    ball_speed_ms: float
    launch_angle_rad: float
    launch_direction_rad: float
    spin_rate_rad_s: float
    spin_axis_rad: float
    air_density: float = RHO_SEA_LEVEL
    # carry the source/club through for grouping; measured carry is the
    # calibration target (yards, as recorded) when present.
    source: str = ""
    club: str = ""
    measured_carry_yards: float | None = None
    measured_total_yards: float | None = None  # carry + roll, when the monitor reports it


def _f(value: object) -> float | None:
    """Coerce a possibly-missing/NaN value to float or None."""
    if not isinstance(value, (int, float, str)) or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def from_fct_row(row: dict) -> ShotInput | None:
    """Map a `fct_shots` row (mph / deg / rpm / yards) into a SI ShotInput.

    Returns None if the row lacks the fields the physics engine requires
    (ball speed, launch angle, spin rate) - the caller filters those out.
    Missing optional shape fields (spin axis, launch direction) default to 0.
    """
    ball = _f(row.get("ball_speed_mph"))
    launch = _f(row.get("launch_angle_deg"))
    spin = _f(row.get("spin_rate_rpm"))
    if ball is None or launch is None or spin is None:
        return None

    return ShotInput(
        ball_speed_ms=ball * MPH_TO_MS,
        launch_angle_rad=math.radians(launch),
        launch_direction_rad=math.radians(_f(row.get("launch_direction_deg")) or 0.0),
        spin_rate_rad_s=spin * RPM_TO_RAD_S,
        spin_axis_rad=math.radians(_f(row.get("spin_axis_deg")) or 0.0),
        source=str(row.get("source", "")),
        club=str(row.get("club", "")),
        measured_carry_yards=_f(row.get("carry_yards")),
        measured_total_yards=_f(row.get("total_yards")),
    )

"""Cited benchmark reference data for the modeling engine.

External, published golf benchmarks (TrackMan tour averages, …) live here as
small committed CSVs with provenance in SOURCES.md. This module loads them into
typed rows and maps them onto the engine's `ShotInput` contract, so a tour bag
can be flown through the physics engine and compared to its published carry.
"""

from __future__ import annotations

import csv
import functools
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..contracts import MPH_TO_MS, RPM_TO_RAD_S, ShotInput

if TYPE_CHECKING:
    from ..calibration import CalibrationResult

_DIR = Path(__file__).parent
_TRACKMAN_PGA = _DIR / "trackman_pga_tour_averages.csv"
_TRACKMAN_LPGA = _DIR / "trackman_lpga_tour_averages.csv"


@dataclass(frozen=True)
class TourClub:
    """One club's published launch-monitor averages (mph / deg / rpm / yards)."""

    club: str
    club_speed_mph: float
    attack_angle_deg: float
    ball_speed_mph: float
    smash_factor: float
    launch_angle_deg: float
    spin_rate_rpm: float
    max_height_yards: float
    land_angle_deg: float
    carry_yards: float

    def to_shot_input(self) -> ShotInput:
        """Map the averages onto the physics contract (SI units).

        Tour averages have no side data, so launch direction and spin axis are
        zero - a straight shot. The published carry rides along as the validation
        target.
        """
        return ShotInput(
            ball_speed_ms=self.ball_speed_mph * MPH_TO_MS,
            launch_angle_rad=math.radians(self.launch_angle_deg),
            launch_direction_rad=0.0,
            spin_rate_rad_s=self.spin_rate_rpm * RPM_TO_RAD_S,
            spin_axis_rad=0.0,
            source="trackman_pga_avg",
            club=self.club,
            measured_carry_yards=self.carry_yards,
        )


def _load(path: Path) -> list[TourClub]:
    with path.open(newline="") as f:
        return [
            TourClub(
                club=row["club"],
                club_speed_mph=float(row["club_speed_mph"]),
                attack_angle_deg=float(row["attack_angle_deg"]),
                ball_speed_mph=float(row["ball_speed_mph"]),
                smash_factor=float(row["smash_factor"]),
                launch_angle_deg=float(row["launch_angle_deg"]),
                spin_rate_rpm=float(row["spin_rate_rpm"]),
                max_height_yards=float(row["max_height_yards"]),
                land_angle_deg=float(row["land_angle_deg"]),
                carry_yards=float(row["carry_yards"]),
            )
            for row in csv.DictReader(f)
        ]


def load_trackman_pga() -> list[TourClub]:
    """The TrackMan PGA Tour averages bag, driver through pitching wedge."""
    return _load(_TRACKMAN_PGA)


def load_trackman_lpga() -> list[TourClub]:
    """The TrackMan LPGA Tour averages bag (driver through wedge; has a 7-wood)."""
    return _load(_TRACKMAN_LPGA)


@functools.cache
def calibrate_engine() -> CalibrationResult:
    """Calibrate the engine's aero coefficients against the TrackMan tour bag.

    The bag spans driver-through-wedge spin, so it pins down the spin-drag term
    a single-club fit can't. This is the engine's coefficient source - no
    warehouse needed; it reads the committed reference CSV. Cached: the fit is
    deterministic and reused by every bag build, so it runs once per process.
    """
    from ..calibration import calibrate  # lazy: keeps the collector free of scipy

    return calibrate([c.to_shot_input() for c in load_trackman_pga()])

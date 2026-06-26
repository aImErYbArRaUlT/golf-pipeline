"""Playing conditions - air density and wind.

The engine already integrates against an air density; this turns the things a
golfer actually feels - temperature, altitude, wind - into the numbers the physics
needs, so you can re-fly a shot "what if it's 5C at altitude into a 15 mph wind".
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from .contracts import MPH_TO_MS, RHO_SEA_LEVEL
from .physics import simulate_batch

if TYPE_CHECKING:
    from .bag import ClubBag
    from .benchmarks import TourClub

# Standard atmosphere constants.
_R = 287.05  # specific gas constant for dry air, J/(kg·K)
_LAPSE = 0.0065  # temperature lapse rate, K/m
_T0_K = 288.15  # sea-level standard temperature, K
_P0 = 101325.0  # sea-level standard pressure, Pa
_G = 9.80665


def air_density(temp_c: float = 15.0, altitude_m: float = 0.0) -> float:
    """Air density (kg/m^3) for a temperature and altitude (standard atmosphere).

    Colder, lower, denser air = more drag = shorter carry; hot or high = thinner
    air = longer. Sea-level 15C returns ~1.225, the engine's default.
    """
    pressure = _P0 * (1.0 - _LAPSE * altitude_m / _T0_K) ** (_G / (_R * _LAPSE))
    return pressure / (_R * (temp_c + 273.15))


def wind_vector(speed_mph: float, from_deg: float) -> np.ndarray:
    """Wind velocity (m/s) in engine axes - x downrange, y lateral (+right), z up.

    `from_deg` is the direction the wind blows *from*, relative to the target line:
    0 = headwind (in your face), 180 = tailwind (at your back), 90 = from the
    right. The vector points where the wind blows *toward*.
    """
    toward = math.radians(from_deg + 180.0)
    return speed_mph * MPH_TO_MS * np.array([math.cos(toward), math.sin(toward), 0.0])


def relative_wind(speed_mph: float, from_compass_deg: float, hole_bearing_deg: float) -> np.ndarray:
    """Wind vector in a hole's frame for a *fixed compass* wind.

    A wind from compass `from_compass_deg` (0 = N) plays as a headwind on a hole you
    aim toward that bearing and a tailwind coming back. Convert to the angle
    relative to the tee->pin line and reuse `wind_vector` (0 = headwind). So one
    real wind helps some holes and hurts others - what makes a round realistic.
    """
    return wind_vector(speed_mph, (from_compass_deg - hole_bearing_deg) % 360.0)


def adjust_bag_for_conditions(
    bag: ClubBag,
    tour_clubs: list[TourClub],
    *,
    wind: np.ndarray | None = None,
    density: float = RHO_SEA_LEVEL,
) -> ClubBag:
    """Shift a calm bag's landing clouds for wind + air density - no re-Monte-Carlo.

    The expensive Monte-Carlo cloud already captures a club's *spread*; wind and
    thinner/denser air mostly *translate* its centre. So instead of re-dispersing
    (thousands of flights per club), we move each club's whole cloud by how its
    stock shot's landing moves calm -> conditions - one stock flight per club each
    way, both vectorised into a single batch. Near-instant, so wind/altitude can
    drive the whole plan live. Exact for the mean; the (second-order) change in
    spread is neglected.
    """
    wind = np.zeros(3) if wind is None else wind
    if not np.any(wind) and abs(density - RHO_SEA_LEVEL) < 1e-9:
        return bag  # calm at sea level - nothing to do

    by_name = {c.club: c for c in tour_clubs}
    paired = [(cs, by_name.get(cs.dispersion.club)) for cs in bag.clubs]
    stocks = [tc.to_shot_input() for _, tc in paired if tc is not None]
    # Two vectorised flights of the stock shots: calm vs under conditions. A coarse
    # step is plenty - we only need the *difference* in landing, so the step error
    # is systematic and cancels.
    calm = simulate_batch(stocks, bag.cd, bag.cl, bag.cd_spin, dt=0.01, t_max=12.0)
    cond = simulate_batch(
        [replace(s, air_density=density) for s in stocks],
        bag.cd,
        bag.cl,
        bag.cd_spin,
        wind=wind,
        dt=0.01,
        t_max=12.0,
    )
    d_carry = cond.carry_yards - calm.carry_yards
    d_lat = cond.lateral_yards - calm.lateral_yards

    new_clubs = []
    k = 0
    for cs, tc in paired:
        if tc is None:
            new_clubs.append(cs)
            continue
        dc, dl = float(d_carry[k]), float(d_lat[k])
        k += 1
        d = cs.dispersion
        shifted = replace(
            d,
            landings_carry=d.landings_carry + dc,
            landings_lateral=d.landings_lateral + dl,
            carry_mean_yards=d.carry_mean_yards + dc,
            lateral_mean_yards=d.lateral_mean_yards + dl,
            carry_p10_yards=d.carry_p10_yards + dc,
            carry_p90_yards=d.carry_p90_yards + dc,
        )
        new_clubs.append(
            replace(cs, dispersion=shifted, measured_carry_mean=cs.measured_carry_mean + dc)
        )

    new_clubs.sort(key=lambda s: s.dispersion.carry_mean_yards, reverse=True)
    return replace(bag, clubs=new_clubs)

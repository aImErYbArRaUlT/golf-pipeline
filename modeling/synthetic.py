"""Synthetic shot generator - realistic dispersion from tour means + a skill knob.

The real launch-monitor data we have is either tour *averages* (means only, no
spread) or one wildly inconsistent amateur. To demo the engine on clean,
believable data - and to drive the planner and the app without a warehouse - we
synthesize per-club shots: take a tour club's mean launch conditions and scatter
them by a skill level, then fly them through the calibrated engine.

The spreads are heuristic, not fit from data: published consistency figures for a
tour pro (ball speed ~1%, launch ~0.7 deg, spin ~4%, a little offline), widened
for lower skill. A single `consistency` scalar scales them, so a UI can expose one
slider. This is the honest, transparent choice - the knob is explicit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from .bag import ClubBag, ClubStats
from .benchmarks import TourClub, calibrate_engine, load_trackman_lpga, load_trackman_pga
from .contracts import ShotInput
from .dispersion import ClubDispersion, simulate_dispersion


def _anchor_carry(disp: ClubDispersion, target_mean: float) -> ClubDispersion:
    """Shift a club's carry distribution onto the published tour carry.

    Trusted *location* from the data (the engine's whole-bag fit leaves a few-yard
    per-club residual - e.g. it under-carries the driver), validated *spread* from
    the engine. So a synthetic driver carries the published 282, not the sim 272.
    """
    shift = target_mean - disp.carry_mean_yards
    return replace(
        disp,
        landings_carry=disp.landings_carry + shift,
        carry_mean_yards=target_mean,
        carry_p10_yards=disp.carry_p10_yards + shift,
        carry_p90_yards=disp.carry_p90_yards + shift,
    )


@dataclass(frozen=True)
class SkillLevel:
    """Shot-to-shot spread of launch conditions, by variable."""

    name: str
    ball_speed_frac: float  # std as a fraction of mean ball speed
    launch_deg: float  # std of launch angle (degrees)
    spin_frac: float  # std as a fraction of mean spin
    direction_deg: float  # std of launch direction (degrees, offline)
    spin_axis_deg: float  # std of spin axis (degrees, curve)

    def scaled(self, factor: float) -> SkillLevel:
        """Widen (or tighten) every spread by `factor` - the UI's one knob."""
        return replace(
            self,
            ball_speed_frac=self.ball_speed_frac * factor,
            launch_deg=self.launch_deg * factor,
            spin_frac=self.spin_frac * factor,
            direction_deg=self.direction_deg * factor,
            spin_axis_deg=self.spin_axis_deg * factor,
        )


# Presets tuned so the landing dispersion matches real shot patterns, not just launch
# consistency. A tour pro lands a driver about 15 yds offline (1 sigma) and a 9-iron about
# 7, finding a big green ~95% from 150 yds and leaving ~19 ft; the spread grows sensibly
# through scratch, mid, and senior. The offline and curve angles are kept modest so the
# long clubs do not spray (curve grows with distance); ball speed carries the distance miss.
TOUR = SkillLevel("tour", 0.016, 0.8, 0.05, 2.0, 3.4)
SCRATCH = SkillLevel("scratch", 0.028, 1.1, 0.07, 3.6, 5.6)
AMATEUR = SkillLevel("amateur", 0.052, 1.9, 0.11, 6.8, 9.5)

_PRESETS = {p.name: p for p in (TOUR, SCRATCH, AMATEUR)}
_TOURS = {"pga": load_trackman_pga, "lpga": load_trackman_lpga}

# Memoized whole-bag builds, keyed on the build arguments (see `synthetic_bag`).
_BAG_CACHE: dict[tuple, ClubBag] = {}


def skill_from_name(name: str) -> SkillLevel:
    """Look up a preset by name (tour / scratch / amateur)."""
    try:
        return _PRESETS[name]
    except KeyError:
        raise ValueError(f"unknown skill {name!r}; choose from {sorted(_PRESETS)}") from None


def synthesize_club_shots(
    club: TourClub, skill: SkillLevel, n: int = 200, seed: int = 0, dist_scale: float = 1.0
) -> list[ShotInput]:
    """Sample `n` shots scattered around a tour club's mean launch conditions.

    `dist_scale` scales ball speed so a slower player carries proportionally less -
    the lever that turns the tour bag into a long amateur, a senior, etc.
    """
    base = club.to_shot_input()
    mean = replace(base, ball_speed_ms=base.ball_speed_ms * dist_scale)
    rng = np.random.default_rng(seed)
    ball = rng.normal(mean.ball_speed_ms, mean.ball_speed_ms * skill.ball_speed_frac, n)
    ball = np.clip(ball, 1.0, None)
    launch = rng.normal(mean.launch_angle_rad, math.radians(skill.launch_deg), n)
    spin = np.clip(
        rng.normal(mean.spin_rate_rad_s, mean.spin_rate_rad_s * skill.spin_frac, n), 0.0, None
    )
    direction = rng.normal(0.0, math.radians(skill.direction_deg), n)
    axis = rng.normal(0.0, math.radians(skill.spin_axis_deg), n)
    return [
        ShotInput(
            ball_speed_ms=float(ball[i]),
            launch_angle_rad=float(launch[i]),
            launch_direction_rad=float(direction[i]),
            spin_rate_rad_s=float(spin[i]),
            spin_axis_rad=float(axis[i]),
            source="synthetic",
            club=club.club,
        )
        for i in range(n)
    ]


def synthetic_bag(
    tour: str = "pga",
    skill: SkillLevel = SCRATCH,
    *,
    dist_scale: float = 1.0,
    n_per_club: int = 200,
    n_samples: int = 2000,
    seed: int = 0,
    clubs: list[str] | None = None,
) -> ClubBag:
    """A `ClubBag` built from a tour's mean launch conditions at a given skill.

    Interchangeable with `bag.load_bag` (the runners, planner and app accept
    either). For synthetic shots the "measured" stats are the synthetic truth, so
    `measured_*` carry the sampled distribution's own mean/std. `dist_scale` shrinks
    every distance for a slower player (a senior, a junior), so the same machinery
    yields different *people*, each with their own optimal way round.
    """
    if tour not in _TOURS:
        raise ValueError(f"unknown tour {tour!r}; choose from {sorted(_TOURS)}")
    # The build is deterministic in its arguments and the Monte-Carlo is the engine's
    # slowest step, so memoize the common (whole-bag) case: a profile rebuilt across
    # tabs or tests is then free. `clubs=` subsets skip the cache (rare, and the key
    # would be a list).
    key = (tour, skill, dist_scale, n_per_club, n_samples, seed)
    if clubs is None and key in _BAG_CACHE:
        return _BAG_CACHE[key]
    table = _TOURS[tour]()
    if clubs is not None:
        wanted = set(clubs)
        table = [c for c in table if c.club in wanted]

    calib = calibrate_engine()
    stats: list[ClubStats] = []
    for i, club in enumerate(table):
        shots = synthesize_club_shots(club, skill, n_per_club, seed + i, dist_scale)
        disp = simulate_dispersion(
            shots,
            source="synthetic",
            player=f"{tour.upper()} {skill.name}",
            club=club.club,
            cd=calib.cd,
            cl_coeff=calib.cl,
            cd_spin=calib.cd_spin,
            n_samples=n_samples,
            seed=seed + i,
        )
        disp = _anchor_carry(disp, club.carry_yards * dist_scale)  # published carry, scaled
        stats.append(
            ClubStats(
                dispersion=disp,
                measured_carry_mean=disp.carry_mean_yards,
                measured_carry_std=disp.carry_std_yards,
                measured_side_std=disp.lateral_std_yards,
            )
        )

    stats.sort(key=lambda s: s.dispersion.carry_mean_yards, reverse=True)
    bag = ClubBag(
        source=f"synthetic-{tour}",
        player=f"{tour.upper()} {skill.name}",
        cd=calib.cd,
        cl=calib.cl,
        cd_spin=calib.cd_spin,
        clubs=stats,
    )
    if clubs is None:
        _BAG_CACHE[key] = bag
    return bag


def resolve_bag(skill_name: str | None, *, tour: str = "pga") -> ClubBag:
    """A `ClubBag` for the runners: a skill name picks a synthetic bag, else the
    real warehouse bag. Lets a demo run clean (and warehouse-free) on request."""
    if skill_name:
        return synthetic_bag(tour, skill_from_name(skill_name))
    from . import warehouse  # lazy: synthetic stays importable without BigQuery
    from .bag import load_bag

    return load_bag(warehouse.client())

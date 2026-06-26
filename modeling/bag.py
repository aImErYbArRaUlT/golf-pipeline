"""Load one player's club bag with per-club dispersion (shared by the runners).

Both the dispersion and scoring runners want the same thing: calibrate the engine
(on the TrackMan tour bag), find the player with the richest set of well-sampled
clubs, and characterise each club's shot dispersion plus what the monitor actually
reported for it. This is that orchestration in one place.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from . import warehouse
from .benchmarks import calibrate_engine
from .contracts import from_fct_row
from .dispersion import MIN_SHOTS, ClubDispersion, simulate_dispersion

_TRIM_PCT = 5  # drop the slowest/fastest 5% of strikes (gross mishits) per club


@dataclass(frozen=True)
class ClubStats:
    """A club's simulated dispersion alongside the monitor's reported spread."""

    dispersion: ClubDispersion
    measured_carry_mean: float
    measured_carry_std: float
    measured_side_std: float


@dataclass(frozen=True)
class ClubBag:
    source: str
    player: str
    cd: float
    cl: float
    cd_spin: float
    clubs: list[ClubStats]  # sorted by carry, longest first


def _group_rows(rows: list[dict]) -> dict[tuple[str, str, str], list[dict]]:
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in rows:
        key = (str(r.get("source", "")), str(r.get("player", "")), str(r.get("club", "")))
        groups[key].append(r)
    return groups


def _pick_player(groups: dict[tuple[str, str, str], list[dict]]) -> tuple[str, str]:
    """The (source, player) with the most clubs that clear MIN_SHOTS."""
    by_player: dict[tuple[str, str], int] = defaultdict(int)
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for (source, player, _club), rows in groups.items():
        totals[(source, player)] += len(rows)
        if len(rows) >= MIN_SHOTS:
            by_player[(source, player)] += 1
    return max(by_player or totals, key=lambda k: (by_player.get(k, 0), totals[k]))


def _trim_mishits(rows: list[dict]) -> list[dict]:
    """Drop ball-speed outliers so a club's dispersion reflects normal strikes."""
    speeds = np.array([r["ball_speed_mph"] for r in rows if r.get("ball_speed_mph") is not None])
    if speeds.size < MIN_SHOTS:
        return rows
    lo, hi = np.percentile(speeds, [_TRIM_PCT, 100 - _TRIM_PCT])
    kept = [
        r for r in rows if r.get("ball_speed_mph") is not None and lo <= r["ball_speed_mph"] <= hi
    ]
    return kept if len(kept) >= MIN_SHOTS else rows


def _reported(rows: list[dict], key: str) -> tuple[float, float]:
    """(mean, std) of a column the monitor reported, over rows where present."""
    vals = np.array([r[key] for r in rows if r.get(key) is not None], dtype=float)
    if vals.size < 2:
        return (math.nan, math.nan)
    return (float(vals.mean()), float(vals.std()))


def load_bag(bq, *, n_samples: int = 2000, max_clubs: int = 6) -> ClubBag:
    """Calibrate (on the tour bag), pick the richest-bag player, disperse their clubs."""
    calib = calibrate_engine()
    groups = _group_rows(warehouse.fetch_rows(bq, warehouse.HAS_LAUNCH_INPUTS))
    source, player = _pick_player(groups)

    club_rows = sorted(
        (
            (club, grp)
            for (src, plr, club), grp in groups.items()
            if src == source and plr == player and len(grp) >= MIN_SHOTS
        ),
        key=lambda cg: len(cg[1]),
        reverse=True,
    )[:max_clubs]

    stats: list[ClubStats] = []
    for club, grp in club_rows:
        rows = _trim_mishits(grp)
        shots = [s for s in (from_fct_row(r) for r in rows) if s is not None]
        disp = simulate_dispersion(
            shots,
            source=source,
            player=player,
            club=club,
            cd=calib.cd,
            cl_coeff=calib.cl,
            cd_spin=calib.cd_spin,
            n_samples=n_samples,
        )
        carry_mean, carry_std = _reported(rows, "carry_yards")
        _, side_std = _reported(rows, "side_dispersion")
        stats.append(ClubStats(disp, carry_mean, carry_std, side_std))

    stats.sort(key=lambda s: s.dispersion.carry_mean_yards, reverse=True)
    return ClubBag(
        source=source, player=player, cd=calib.cd, cl=calib.cl, cd_spin=calib.cd_spin, clubs=stats
    )

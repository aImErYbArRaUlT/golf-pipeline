"""Shot-selection optimiser over a 2-D hole (Stage E).

Where physics (A) + dispersion (B) + scoring (C) + geometry (E) become advice in
two dimensions. A candidate is a club aimed at a point (downrange, lateral);
aiming shifts the landing cloud's centre and keeps its spread. Each sampled ball
is placed on the hole - green, fairway, rough, bunker, or water - and scored:
penalty hazards cost a stroke plus a replay from the drop, every other lie its
benchmark cost to hole out. The optimiser searches aim points to minimise the
expected strokes to hole out, now trading off long/short *and* left/right.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .course import Hole
from .scoring import GREEN, approach_strokes, expected_strokes_array

_DEFAULT_DROP_BACK = 30.0  # if a penalty hazard names no drop, replay from this far short


@dataclass(frozen=True)
class ShotEval:
    """Outcome of aiming one club at one point on the hole."""

    expected_strokes: float
    penalty_pct: float  # share of shots finishing in a penalty hazard
    frac_on_green: float  # share finishing puttable (and dry)
    mean_proximity_yards: float  # mean distance left, balls that stayed in play


@dataclass(frozen=True)
class ShotChoice:
    """A club aimed at its best point on the hole."""

    club: str
    aim_distance_yards: float
    aim_lateral_yards: float
    expected_strokes: float
    penalty_pct: float
    frac_on_green: float
    mean_proximity_yards: float


def evaluate_shot(
    carry_samples: np.ndarray,
    lateral_samples: np.ndarray,
    aim_distance: float,
    aim_lateral: float,
    hole: Hole,
) -> ShotEval:
    """Expected strokes to hole out for aiming a club at (aim_distance, aim_lateral)."""
    carry = np.asarray(carry_samples, dtype=float)
    lat = np.asarray(lateral_samples, dtype=float)
    x = carry - carry.mean() + aim_distance  # downrange landing
    y = lat - lat.mean() + aim_lateral  # lateral landing

    remaining = hole.remaining_yards(x, y)
    rest = expected_strokes_array(remaining, hole.lie_at(x, y))

    penalty = np.zeros(x.shape, dtype=bool)
    for hz in hole.hazards:
        if not hz.is_penalty:
            continue
        mask = hz.region.contains(x, y)
        if mask.any():
            drop = hz.drop_distance
            if drop is None:
                drop = hole.pin_distance_yards - _DEFAULT_DROP_BACK
            drop_cost = hz.penalty_strokes + float(
                approach_strokes(abs(hole.pin_distance_yards - drop))
            )
            rest = np.where(mask, drop_cost, rest)
            penalty |= mask

    dry = ~penalty
    on_green = (hole.lie_at(x, y) == GREEN) & dry
    return ShotEval(
        expected_strokes=1.0 + float(rest.mean()),
        penalty_pct=float(penalty.mean()),
        frac_on_green=float(on_green.mean()),
        mean_proximity_yards=float(remaining[dry].mean()) if dry.any() else float("nan"),
    )


def optimize_shot(
    clubs: list[tuple[str, np.ndarray, np.ndarray]],
    hole: Hole,
    *,
    aim_short: float = 30.0,
    aim_long: float = 12.0,
    lateral_span: float = 24.0,
    step: float = 3.0,
) -> list[ShotChoice]:
    """Best (club, aim point) per club, ranked by expected strokes (lowest first).

    Each club is searched over a grid of aim points: downrange from `aim_short`
    short of its stock carry to `aim_long` past, lateral within +/-`lateral_span`.
    """
    out: list[ShotChoice] = []
    for name, carry, lateral in clubs:
        stock = float(np.asarray(carry, dtype=float).mean())
        dist_aims = np.arange(stock - aim_short, stock + aim_long + 1e-9, step)
        dist_aims = dist_aims[dist_aims >= 1.0]
        if dist_aims.size == 0:
            dist_aims = np.array([stock])
        lat_aims = np.arange(-lateral_span, lateral_span + 1e-9, step)

        best: ShotChoice | None = None
        for ad in dist_aims:
            for al in lat_aims:
                ev = evaluate_shot(carry, lateral, float(ad), float(al), hole)
                if best is None or ev.expected_strokes < best.expected_strokes:
                    best = ShotChoice(
                        club=name,
                        aim_distance_yards=float(ad),
                        aim_lateral_yards=float(al),
                        expected_strokes=ev.expected_strokes,
                        penalty_pct=ev.penalty_pct,
                        frac_on_green=ev.frac_on_green,
                        mean_proximity_yards=ev.mean_proximity_yards,
                    )
        assert best is not None
        out.append(best)

    out.sort(key=lambda c: c.expected_strokes)
    return out

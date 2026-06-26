"""Strokes-gained scoring (Stage C).

The value layer. Stage A flies a shot, Stage B says where a club's shots scatter;
this turns a position - and a whole landing distribution - into a number: the
expected strokes to hole out. That number is what a strategy optimiser (Stage D)
minimises, and the difference between two positions' numbers is *strokes gained*.

The baseline `expected_strokes(distance, lie)` is the standard tour benchmark
popularised by Mark Broadie ("Every Shot Counts"): the average strokes a
benchmark player takes to hole out from a given distance and lie. The anchor
values below are the commonly-published PGA-Tour averages (approximate); the
model interpolates between them. We assert the *shape* (monotone in distance,
rough worse than fairway, putting cheaper than approach) in the tests rather than
claiming the decimals to three places.

Distances are yards for approach lies and converted to feet for putting.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TEE = "tee"
FAIRWAY = "fairway"
ROUGH = "rough"
SAND = "sand"
RECOVERY = "recovery"
GREEN = "green"
LIES = frozenset({TEE, FAIRWAY, ROUGH, SAND, RECOVERY, GREEN})

# Published PGA-Tour benchmark - average strokes to hole out by distance (yards)
# and lie, from Broadie, "Assessing Golfer Performance on the PGA TOUR" (ShotLink
# 2003-2010) and "Every Shot Counts". Verified anchors from that work: fairway
# 100yd=2.80 and 120yd=2.85, rough 120yd=3.08 (a 0.23 penalty), sand 5yd=2.37.
# Values between the published distances are interpolated.
# fmt: off
_DIST     = np.array([5,    10,   20,   30,   40,   50,   60,   70,   80,   90,   100,  120,  140,  160,  180,  200,  220,  240])  # noqa: E501
_FAIRWAY  = np.array([2.05, 2.18, 2.40, 2.52, 2.58, 2.63, 2.67, 2.70, 2.72, 2.75, 2.80, 2.85, 2.91, 2.98, 3.08, 3.19, 3.30, 3.40])  # noqa: E501
_ROUGH    = np.array([2.15, 2.34, 2.59, 2.70, 2.78, 2.85, 2.88, 2.91, 2.93, 2.97, 3.02, 3.08, 3.15, 3.23, 3.31, 3.39, 3.48, 3.57])  # noqa: E501
_SAND     = np.array([2.37, 2.45, 2.53, 2.66, 2.82, 2.92, 2.99, 3.03, 3.06, 3.09, 3.10, 3.14, 3.19, 3.23, 3.29, 3.36, 3.43, 3.51])  # noqa: E501
_RECOVERY = np.array([3.30, 3.35, 3.45, 3.52, 3.58, 3.63, 3.68, 3.72, 3.76, 3.78, 3.80, 3.82, 3.84, 3.87, 3.91, 3.97, 4.04, 4.11])  # noqa: E501

# Putting (feet -> strokes), Broadie's average-putts benchmark (his Figure 4).
_PUTT_FT = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 25, 30, 40, 50, 60, 90])
_PUTT_ES = np.array([1.001, 1.01, 1.04, 1.13, 1.23, 1.34, 1.42, 1.50, 1.56, 1.61,
                     1.78, 1.87, 1.93, 1.98, 2.06, 2.14, 2.21, 2.40])
# fmt: on

_LIE_TABLE = {FAIRWAY: _FAIRWAY, ROUGH: _ROUGH, SAND: _SAND, RECOVERY: _RECOVERY}

# Tee benchmark: Broadie's linear fit of average score on hole length (yards).
_TEE_INTERCEPT, _TEE_SLOPE = 2.38, 0.0041

# How much of the short-game skill gap lands on putting vs the rest of the short game.
# Strokes-gained data has the amateur-to-tour gap larger per shot around the green than
# on it, so putting carries a fraction of the tax - which also makes a green miss dearer
# than a putt, so a weak short game aims for the fat of the green, not just a worse score.
_PUTT_SG_WEIGHT = 0.6

# A green's own difficulty (its slope/speed - an objective property read from the map)
# taxes the makeable putts on top of the player's skill, and more for a weak putter than
# a tour pro (the interaction). It is the green's, not the player's: difficulty is shared
# across users; short_game is per-user; the cost is their product. 0 = a benchmark-average
# green; ~1 = a severe (~2.5% tilt) one.
_GREEN_DIFF_BASE = 0.18  # the tax a hard green puts on everyone, tour included
_GREEN_DIFF_SKILL = 0.55  # the extra tax on a weak putter (× short_game)
# A hard green isn't only a putting tax - it's harder to chip and pitch *to* (the runoffs,
# the short side), so it taxes the whole around-the-green zone, not just the putt. That is
# what makes a severe green cost a weaker player (more around it) more than a tour pro.
_GREEN_ZONE_YARDS = 30.0

# Within this of the pin a ball at rest is treated as on the green (a putt);
# beyond it, a short-game shot from the fairway. A simplification until Stage E
# gives real green geometry - it shifts absolute scores, not club-to-club ranking.
GREEN_RADIUS_YARDS = 5.0


@dataclass(frozen=True)
class HoleOutScore:
    """Expected cost of holing out from a landing distribution."""

    expected_strokes: float  # mean strokes to hole out, this shot included
    mean_proximity_yards: float  # average distance left to the pin
    frac_on_green: float  # share of the distribution finishing puttable


def expected_strokes(distance_yards: float, lie: str) -> float:
    """Benchmark strokes to hole out from a distance and lie (0 if holed)."""
    if distance_yards <= 0.0:
        return 0.0
    if lie == GREEN:
        return float(np.interp(distance_yards * 3.0, _PUTT_FT, _PUTT_ES))
    if lie == TEE:
        return _TEE_INTERCEPT + _TEE_SLOPE * distance_yards
    table = _LIE_TABLE.get(lie)
    if table is None:
        raise ValueError(f"unknown lie: {lie!r}")
    return float(np.interp(distance_yards, _DIST, table))


def strokes_gained(
    start_distance_yards: float,
    start_lie: str,
    end_distance_yards: float,
    end_lie: str,
    *,
    penalty_strokes: float = 0.0,
) -> float:
    """Strokes gained by one shot: expected(start) - expected(end) - 1 - penalties.

    Positive means the shot beat the benchmark, negative means it lost ground.
    """
    return (
        expected_strokes(start_distance_yards, start_lie)
        - expected_strokes(end_distance_yards, end_lie)
        - 1.0
        - penalty_strokes
    )


def approach_strokes(distance_yards: np.ndarray) -> np.ndarray:
    """Vectorised fairway-lie strokes to hole out (no per-lie penalty added)."""
    return np.interp(distance_yards, _DIST, _FAIRWAY)


def putt_strokes(distance_yards: np.ndarray) -> np.ndarray:
    """Vectorised putting strokes to hole out (yards converted to feet)."""
    return np.interp(np.asarray(distance_yards, dtype=float) * 3.0, _PUTT_FT, _PUTT_ES)


def expected_strokes_array(
    distances_yards: np.ndarray,
    lies: np.ndarray,
    *,
    short_game: float = 0.0,
    green_difficulty: float = 0.0,
) -> np.ndarray:
    """Vectorised expected strokes for arrays of (distance, lie).

    Handles the green (putting curve) and every approach lie (per-lie table) in
    one pass - what a 2-D hole's landing cloud needs.

    `short_game` makes this *the player's* short game and putting rather than the
    tour benchmark: 0 is tour; higher scales up the strokes a player needs *above*
    holing the next one (`base + short_game·weight·(base - 1)`). It scales with
    difficulty, so a long putt or a bunker shot is taxed heavily while a tap-in barely
    moves. The `weight` is heavier off the green than on it, because the amateur-to-
    tour gap is larger per shot around the green (chips, pitches, bunkers) than on it
    (putts) - and, unlike a flat scale, that makes a miss off the green cost *more*
    than a putt, so a weaker short game leans the aim onto the fat of the green rather
    than only inflating the score. The benchmark owns the full swing (modelled by
    dispersion); this curve is only evaluated near the green, so it is the around-and-
    on-the-green skill it claims to be.
    """
    d = np.asarray(distances_yards, dtype=float)
    out = np.full(d.shape, np.nan)
    green = lies == GREEN
    out[green] = putt_strokes(d[green])
    for lie, table in _LIE_TABLE.items():
        m = lies == lie
        out[m] = np.interp(d[m], _DIST, table)
    # Tax the strokes *above* holing the next one - the part skill and green difficulty
    # move. Off the green it's all short-game skill; on it, the player's putting plus the
    # green's own difficulty (objective, from the map), which bites a weak putter harder.
    tax = short_game * np.where(green, _PUTT_SG_WEIGHT, 1.0)
    if green_difficulty:
        # The green and everything around it (chips/pitches in) is harder, and harder for
        # a weaker player - so the amateur, who is around the green more, pays more than
        # the pro who is mostly putting it.
        near = green | (d <= _GREEN_ZONE_YARDS)
        tax = tax + near * green_difficulty * (_GREEN_DIFF_BASE + _GREEN_DIFF_SKILL * short_game)
    if short_game or green_difficulty:
        out = out + tax * (out - 1.0)
    return out


def hole_out_strokes(
    pin_distance_yards: float,
    carry_samples: np.ndarray,
    *,
    lateral_samples: np.ndarray | None = None,
    green_radius_yards: float = GREEN_RADIUS_YARDS,
) -> HoleOutScore:
    """Expected strokes to hole out over a Monte-Carlo landing distribution.

    Aim at a pin `pin_distance_yards` downrange; each sampled shot finishes at
    `carry_samples` (and `lateral_samples` if given). The remaining distance sets
    the next shot's cost - a putt if it finished within the green radius, else a
    short-game/approach shot from the fairway. This is the value a Stage-D
    optimiser minimises over aim points and clubs.
    """
    carry = np.asarray(carry_samples, dtype=float)
    if lateral_samples is None:
        remaining = np.abs(pin_distance_yards - carry)
    else:
        remaining = np.hypot(pin_distance_yards - carry, np.asarray(lateral_samples, dtype=float))

    on_green = remaining <= green_radius_yards
    rest = np.where(on_green, putt_strokes(remaining), approach_strokes(remaining))
    return HoleOutScore(
        expected_strokes=1.0 + float(rest.mean()),
        mean_proximity_yards=float(remaining.mean()),
        frac_on_green=float(on_green.mean()),
    )

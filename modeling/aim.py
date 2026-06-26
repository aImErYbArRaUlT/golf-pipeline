"""Where to aim an approach, given the flag and your dispersion.

The whole-hole planner aims to a green's centre; this answers the golfer's real
question: with *this* pin and *my* scatter, where do I aim? It flies the club's
dispersion cloud at a grid of targets around the flag, prices each by expected
strokes to hole out (proximity on the green, the lie off it, a penalty in water),
and returns the strokes-gained-optimal aim - as plain yards short/long and
left/right of the flag. So a tight player aims at it; a wide player, or a tucked
pin with a bunker short-right, gets walked to the fat side automatically.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely.geometry import Point
from shapely.ops import nearest_points

from .bag import ClubBag
from .course import CourseHole, Hole
from .scoring import GREEN, expected_strokes_array

_YD_TO_FT = 3.0
_WATER_COST = 1.0  # penalty stroke; the drop's own expected strokes are added below
# Extra putts per yard the ball sits *above* the hole: a downhill putt is faster and
# harder to lag, an uphill one more makeable. So the aim is pulled below the hole.
_SLOPE_PUTT = 0.35
# A legal hole location: at least ~4 paces in from the green's edge, and on a spot gentle
# enough to hold a cut hole. (Our LiDAR over-reads absolute slope, so the slope rule keeps
# the gentler `_LEGAL_SLOPE_Q` fraction of the green *relative* to its own contour.) Only
# legal flags are searched - that's both correct and the search saving.
_LEGAL_INSET = 4.0
_LEGAL_SLOPE_Q = 0.7


def clamp_pin_to_green(
    green, pin: tuple[float, float], *, margin: float = 3.0
) -> tuple[float, float]:
    """Keep a pin on the putting surface - a real flag never sits off the green.

    Pulls the green in by `margin` yards (pins sit a few paces from the edge) and, if
    the requested spot is outside it, snaps to the nearest point inside. Falls back
    to the full green for a tiny one. Returns the on-green pin.
    """
    inner = green.buffer(-margin)
    if inner.is_empty:
        inner = green
    pt = Point(pin)
    if inner.contains(pt):
        return pin
    near = nearest_points(inner, pt)[0]
    return (float(near.x), float(near.y))


@dataclass(frozen=True)
class AimAdvice:
    """A strokes-gained-optimal approach aim, relative to the flag."""

    club: str
    long_yds: float  # + past the flag, - short of it
    right_yds: float  # + right of the flag, - left
    expected: float  # expected strokes to hole out from the approach
    on_green_pct: float  # share of shots that find the green
    proximity_ft: float  # mean distance to the pin for shots on the green


def aim_for_pin(
    hole: Hole | CourseHole,
    bag: ClubBag,
    pin_xy: tuple[float, float],
    from_distance: float,
    *,
    n: int = 700,
    short_game: float = 0.0,
) -> AimAdvice:
    """Best aim for an approach of `from_distance` yards to the pin at `pin_xy`.

    `short_game` is the player's around-and-on-the-green skill (0 = tour): a weaker
    short game prices a miss off the green higher, so the aim leans further onto the
    fat of the green and away from short-side trouble it can't recover from.
    """
    pin_x, pin_y = float(pin_xy[0]), float(pin_xy[1])
    gd = getattr(hole, "green_difficulty", 0.0)  # the green's putting difficulty
    club = min(bag.clubs, key=lambda cs: abs(cs.measured_carry_mean - from_distance))
    d = club.dispersion
    # The club's landing scatter, recentred to zero (the shape of the cloud).
    take = np.linspace(0, len(d.landings_carry) - 1, min(n, len(d.landings_carry))).astype(int)
    carry = d.landings_carry[take] - d.landings_carry.mean()
    lat = d.landings_lateral[take] - d.landings_lateral.mean()

    e_hole = float(hole.elevation_on_green(np.array([pin_x]), np.array([pin_y]))[0])
    best = (float("inf"), 0.0, 0.0, 0.0, float("nan"))
    for d_long in np.arange(-24.0, 9.0, 2.0):  # aim short (-) or long (+) of the flag
        for d_right in np.arange(-20.0, 21.0, 2.0):  # left (-) or right (+)
            lx = pin_x + d_long + carry  # landing downrange / lateral for this aim
            ly = pin_y + d_right + lat
            lie = hole.lie_at(lx, ly)
            on_green = lie == GREEN
            rem = np.hypot(pin_x - lx, pin_y - ly)
            cost = expected_strokes_array(rem, lie, short_game=short_game, green_difficulty=gd)
            # On the green, being above the hole (higher than the pin) is a downhill
            # putt - costlier; below it is uphill and more makeable.
            cost = np.where(
                on_green, cost + _SLOPE_PUTT * (hole.elevation_on_green(lx, ly) - e_hole), cost
            )
            cost = np.where(hole.in_penalty(lx, ly), _WATER_COST + 2.7, cost)
            score = float(cost.mean())
            if score < best[0]:
                prox = float(rem[on_green].mean()) * _YD_TO_FT if on_green.any() else float("nan")
                best = (score, float(d_long), float(d_right), float(on_green.mean()), prox)

    score, d_long, d_right, pct, prox = best
    return AimAdvice(
        club=d.club,
        long_yds=d_long,
        right_yds=d_right,
        expected=score,
        on_green_pct=pct * 100.0,
        proximity_ft=prox,
    )


@dataclass(frozen=True)
class PinDifficulty:
    """One candidate flag and how hard it plays for this player's dispersion."""

    x: float
    y: float
    expected: float  # expected strokes to hole out from the approach, playing it best
    over_easiest: float  # strokes harder than the kindest pin on this green


def pin_difficulty_surface(
    hole: Hole | CourseHole,
    bag: ClubBag,
    *,
    from_distance: float = 160.0,
    short_game: float = 0.0,
    step: float = 3.0,
    n: int = 400,
) -> list[PinDifficulty]:
    """How hard every possible flag position plays, for *this* player's miss.

    Sweeps candidate pins across the green; for each, flies the player's dispersion cloud
    at a few aims (the flag and partway to the fat of the green) and prices the best by
    expected strokes to hole out - so a flag with little room on the miss side (short-sided
    over a bunker, or above a slope) scores higher because even the optimal aim can't keep
    the scatter safe. No survey data: it's the green outline + slope + the player's spread.
    Returns one `PinDifficulty` per candidate pin, sorted easiest first."""
    import numpy as np

    green = getattr(hole, "green", None)
    if green is None or green.is_empty:  # only real (polygon) greens have a surface
        return []
    club = min(bag.clubs, key=lambda cs: abs(cs.measured_carry_mean - from_distance))
    d = club.dispersion
    take = np.linspace(0, len(d.landings_carry) - 1, min(n, len(d.landings_carry))).astype(int)
    cr = d.landings_carry[take] - d.landings_carry.mean()
    lt = d.landings_lateral[take] - d.landings_lateral.mean()
    gd = getattr(hole, "green_difficulty", 0.0)

    # Candidate flags: legal hole locations only - inset from the edge and on a holdable
    # slope - so the expensive cloud pricing runs on far fewer pins (the search saving).
    minx, miny, maxx, maxy = green.bounds
    cand: list[tuple[float, float]] = []
    for inset in (_LEGAL_INSET, 2.0, 0.0):  # ~4 paces in; relax on a small green
        region = green.buffer(-inset) if inset else green
        if region.is_empty:
            continue
        cand = [
            (float(px), float(py))
            for px in np.arange(minx, maxx, step)
            for py in np.arange(miny, maxy, step)
            if region.contains(Point(float(px), float(py)))
        ]
        if cand:
            break
    if cand and len(getattr(hole, "green_quad", ())) >= 6:
        grades = hole.green_grade_at(np.array([c[0] for c in cand]), np.array([c[1] for c in cand]))
        cutoff = float(np.quantile(grades, _LEGAL_SLOPE_Q))  # keep the gentler part
        cand = [c for c, g in zip(cand, grades, strict=True) if g <= cutoff]

    cx, cy = green.centroid.x, green.centroid.y
    out: list[PinDifficulty] = []
    for px, py in cand:
        e_hole = float(hole.elevation_on_green(np.array([px]), np.array([py]))[0])
        best = float("inf")
        for f in (0.0, 0.3, 0.55):  # aim at the flag, or bail toward the fat side
            lx = px + f * (cx - px) + cr
            ly = py + f * (cy - py) + lt
            lie = hole.lie_at(lx, ly)
            rem = np.hypot(px - lx, py - ly)
            cost = expected_strokes_array(rem, lie, short_game=short_game, green_difficulty=gd)
            cost = np.where(
                lie == GREEN,
                cost + _SLOPE_PUTT * (hole.elevation_on_green(lx, ly) - e_hole),
                cost,
            )
            cost = np.where(hole.in_penalty(lx, ly), _WATER_COST + 2.7, cost)
            best = min(best, float(cost.mean()))
        out.append(PinDifficulty(round(px, 1), round(py, 1), round(best, 3), 0.0))

    if not out:
        return []
    easiest = min(p.expected for p in out)
    out = [
        PinDifficulty(p.x, p.y, p.expected, round(p.expected - easiest, 3))
        for p in sorted(out, key=lambda p: p.expected)
    ]
    return out

"""A 2-D hole the optimiser plays (Stage E).

Stage D scored on carry distance alone; this puts the now-validated lateral
dimension to work on real geometry. The hole lives in a plane: x is downrange
(toward the pin), y is lateral (+ = right). A shot finishes at (carry, lateral);
where it finishes - green, fairway, rough, a bunker, or the water - sets what the
next shot costs.

Regions are rectangles (enough for a green-side pond, a fairway bunker, an OB
line) with vectorised membership, so a whole Monte-Carlo cloud is classified at
once. The optimiser above this doesn't care about the shapes - only `lie_at`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import shapely
from shapely import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .scoring import FAIRWAY, GREEN, RECOVERY, ROUGH, SAND

_COURSES_DIR = Path(__file__).parent / "courses"

# Hazard kinds: penalty hazards cost a stroke and a drop; sand is just a lie.
WATER = "water"
OB = "ob"
_PENALTY_KINDS = {WATER, OB}


@dataclass(frozen=True)
class Region:
    """A rectangle in (downrange, lateral) yards."""

    near: float
    far: float
    left: float
    right: float

    def contains(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return (x >= self.near) & (x <= self.far) & (y >= self.left) & (y <= self.right)


@dataclass(frozen=True)
class Hazard:
    region: Region
    kind: str = WATER  # WATER / OB (penalty + drop) or SAND (a lie you play from)
    penalty_strokes: float = 1.0  # for penalty hazards
    drop_distance: float | None = None  # penalty replay point downrange (lateral 0)

    @property
    def is_penalty(self) -> bool:
        return self.kind in _PENALTY_KINDS


@dataclass(frozen=True)
class Hole:
    """Pin, green, fairway corridor and the trouble around them."""

    pin_distance_yards: float
    green_radius_yards: float = 6.0
    fairway_half_width_yards: float = 16.0  # |lateral| within this (off green) = fairway
    hazards: tuple[Hazard, ...] = field(default_factory=tuple)
    green_difficulty: float = 0.0  # putting difficulty (parametric holes default to flat)

    def remaining_yards(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Straight-line distance from each landing point to the pin."""
        return np.hypot(self.pin_distance_yards - x, y)

    def lie_at(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Lie (string array) for landing points, ignoring penalty hazards.

        Penalty hazards are handled by the optimiser (they replay from a drop);
        this returns the lie you'd *play from* otherwise: green, sand, fairway or
        rough.
        """
        remaining = self.remaining_yards(x, y)
        lie = np.where(np.abs(y) <= self.fairway_half_width_yards, FAIRWAY, ROUGH)
        lie = np.where(remaining <= self.green_radius_yards, GREEN, lie)
        for hz in self.hazards:
            if hz.kind == SAND:
                lie = np.where(hz.region.contains(x, y), SAND, lie)
        return lie

    def in_penalty(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Boolean mask: landing points that finished in a penalty hazard."""
        mask = np.zeros(np.shape(x), dtype=bool)
        for hz in self.hazards:
            if hz.is_penalty:
                mask |= hz.region.contains(x, y)
        return mask

    def elevation_at(self, x: np.ndarray) -> np.ndarray:
        """Ground elevation (yards, relative to the tee) at a downrange - flat here."""
        return np.zeros_like(np.asarray(x, dtype=float))

    def elevation_on_green(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Green-surface height (yards) at a point - flat here."""
        return np.zeros_like(np.asarray(x, dtype=float))

    def bounds(self) -> tuple[float, float, float, float]:
        """Grid extent (x_min, x_max, y_min, y_max) in yards the planner grids over."""
        y_ext = max(self.fairway_half_width_yards + 25.0, 40.0)
        return (0.0, self.pin_distance_yards + 40.0, -y_ext, y_ext)

    def penalty_drop_x(self) -> float | None:
        """Downrange of the penalty replay point, or None for the planner default."""
        pen = next((h for h in self.hazards if h.is_penalty), None)
        return pen.drop_distance if pen is not None else None

    def penalty_cost(self) -> float:
        """Stroke penalty for finding water/OB (the first penalty hazard's, or 1)."""
        pen = next((h for h in self.hazards if h.is_penalty), None)
        return pen.penalty_strokes if pen is not None else 1.0


def _polygon(coords: list[list[float]]) -> BaseGeometry:
    """A valid shapely polygon from a coordinate ring (buffer(0) repairs OSM kinks)."""
    if len(coords) < 3:
        return Polygon()
    return Polygon(coords).buffer(0)


def _union(rings: list[list[list[float]]]) -> BaseGeometry:
    polys = [_polygon(r) for r in rings]
    polys = [p for p in polys if not p.is_empty]
    return unary_union(polys) if polys else Polygon()


def _as_rings(x: list) -> list[list[list[float]]]:
    """Normalise a polygon field to a list of rings, accepting either a single ring
    (the legacy one-fairway shape) or a list of rings (a hole's several fairways)."""
    if not x:
        return []
    return x if isinstance(x[0][0], (list, tuple)) else [x]


# Tee levels the app offers, mapped per hole by rank (a hole may have 2-6 tees).
TEE_LEVELS = ("Back", "Middle", "Forward")


@dataclass(frozen=True)
class TeeBox:
    """One tee: where the player starts (downrange/lateral in the hole frame) and
    its straight-line yardage to the pin. A forward tee sits further downrange, so
    it plays shorter."""

    downrange: float
    lateral: float
    yards: float


@dataclass
class CourseHole:
    """A real hole: shapely green/fairway/bunker/water polygons in the engine frame.

    Same interface the planner asks of `Hole` - `pin_distance_yards`,
    `remaining_yards`, `lie_at`, `in_penalty`, `bounds`, `penalty_drop_x` - but
    geometry comes from OpenStreetMap outlines (see `courses/`), not rectangles.
    The pin sits on the downrange axis (lateral 0) by construction, so the
    distance-to-pin formula is unchanged.
    """

    course: str
    ref: int
    par: int
    pin_distance_yards: float
    bearing_deg: float  # compass bearing tee->pin (0 = N), for fixed-wind direction
    green: BaseGeometry  # shapely (Multi)Polygon
    fairway: BaseGeometry
    bunkers: BaseGeometry
    water: BaseGeometry
    _bbox: tuple[float, float, float, float]
    # The playable corridor (fairway + green + a buffer along the mapped route). Ground
    # outside it is trees/junk - a recovery lie you can fly over but not safely land in,
    # which is what forces the planner to route around a dogleg. Empty = no corridor
    # known (the hole is then all fairway/rough, as before).
    playable: BaseGeometry = Polygon()
    tees: tuple[TeeBox, ...] = ()  # tee boxes, longest first
    elevation: tuple[tuple[float, float], ...] = ()  # (downrange, height-vs-tee) yards
    green_slope: tuple[float, float] = (0.0, 0.0)  # elevation gradient (d/downrange, d/lateral)
    green_difficulty: float = 0.0  # putting difficulty from the green's slope severity
    green_quad: tuple[float, ...] = ()  # quadratic surface coeffs, for per-point local slope

    @property
    def label(self) -> str:
        return f"{self.course} - Hole {self.ref} (par {self.par})"

    def elevation_on_green(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Green-surface height (yards) at a point, relative to the green's centre -
        a tilt plane fit to USGS samples. Below the hole = lower than the pin."""
        a, b = self.green_slope
        c = self.green.centroid
        return a * (np.asarray(x, dtype=float) - c.x) + b * (np.asarray(y, dtype=float) - c.y)

    def green_grade_at(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Local green slope (percent) at a point, from the fitted quadratic surface (the
        net plane if none) - how steep it is right there, for judging whether a flag could
        legally be cut on that spot (a hole can't sit on a steep slope)."""
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        q = self.green_quad
        if len(q) >= 6:
            gx = q[1] + 2 * q[3] * x + q[4] * y
            gy = q[2] + q[4] * x + 2 * q[5] * y
        else:
            gx, gy = self.green_slope
        return np.hypot(gx, gy) * 100.0

    def elevation_at(self, x: np.ndarray) -> np.ndarray:
        """Ground elevation (yards, relative to the tee) at a downrange, interpolated
        from the USGS profile. Zero everywhere if the course carries no terrain."""
        x = np.asarray(x, dtype=float)
        if not self.elevation:
            return np.zeros_like(x)
        xs = [p[0] for p in self.elevation]
        ys = [p[1] for p in self.elevation]
        return np.interp(x, xs, ys)  # flat extrapolation past the ends

    def tee_for(self, level: str = "Back") -> TeeBox:
        """The tee box for a course-wide level, mapped to this hole by rank (so a
        hole with only two tees still answers Back / Middle / Forward sensibly)."""
        if not self.tees:
            return TeeBox(0.0, 0.0, self.pin_distance_yards)
        n = len(self.tees)
        idx = {"Back": 0, "Middle": (n - 1) // 2, "Forward": n - 1}.get(level, 0)
        return self.tees[idx]

    def remaining_yards(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return np.hypot(self.pin_distance_yards - x, y)

    def lie_at(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Lie by polygon membership: green > sand > fairway > rough, with ground outside
        the playable corridor a recovery lie (trees/junk you fly over but don't land in)."""
        shp = np.shape(x)
        xf = np.asarray(x, dtype=float).ravel()
        yf = np.asarray(y, dtype=float).ravel()
        lie = np.full(xf.shape, ROUGH, dtype="<U8")
        if not self.playable.is_empty:
            lie[~shapely.contains_xy(self.playable, xf, yf)] = RECOVERY
        if not self.fairway.is_empty:
            lie[shapely.contains_xy(self.fairway, xf, yf)] = FAIRWAY
        if not self.bunkers.is_empty:
            lie[shapely.contains_xy(self.bunkers, xf, yf)] = SAND
        if not self.green.is_empty:
            lie[shapely.contains_xy(self.green, xf, yf)] = GREEN
        return lie.reshape(shp)

    def in_penalty(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        shp = np.shape(x)
        if self.water.is_empty:
            return np.zeros(shp, dtype=bool)
        xf = np.asarray(x, dtype=float).ravel()
        yf = np.asarray(y, dtype=float).ravel()
        return shapely.contains_xy(self.water, xf, yf).reshape(shp)

    def bounds(self) -> tuple[float, float, float, float]:
        return self._bbox

    def penalty_drop_x(self) -> float | None:
        """Lay-up point just short of the water, or None when the hole has none."""
        if self.water.is_empty:
            return None
        return max(0.0, float(self.water.bounds[0]) - 5.0)

    def penalty_cost(self) -> float:
        """One stroke for finding water (standard penalty-area relief)."""
        return 1.0


def load_course(slug: str = "torrey_pines_south") -> list[CourseHole]:
    """Load a committed OSM-derived course into polygon `CourseHole`s (one per hole)."""
    data = json.loads((_COURSES_DIR / f"{slug}.json").read_text())
    holes = []
    for h in data["holes"]:
        fw_rings = _as_rings(h["fairway"])
        green = _polygon(h["green"])
        fairway = _union(fw_rings)
        bunkers = _union(h["bunkers"])
        water = _union(h["water"])
        playable = _union(h.get("playable", []))
        rings = [h["green"], *fw_rings, *h["bunkers"], *h["water"]]
        pts = [p for r in rings for p in r]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bbox = (
            min(0.0, min(xs) - 10.0),
            max(max(xs), h["pin_distance_yards"]) + 20.0,
            min(-40.0, min(ys) - 15.0),
            max(40.0, max(ys) + 15.0),
        )
        tees = tuple(TeeBox(t["downrange"], t["lateral"], t["yards"]) for t in h.get("tees", []))
        elev = tuple((float(p[0]), float(p[1])) for p in h.get("elevation", []))
        gs = h.get("green_slope", [0.0, 0.0])
        holes.append(
            CourseHole(
                course=data["name"],
                ref=h["ref"],
                par=h["par"],
                pin_distance_yards=h["pin_distance_yards"],
                bearing_deg=h.get("bearing_deg", 0.0),
                green=green,
                fairway=fairway,
                bunkers=bunkers,
                water=water,
                _bbox=bbox,
                playable=playable,
                tees=tees,
                elevation=elev,
                green_slope=(float(gs[0]), float(gs[1])),
                green_difficulty=float(h.get("green_difficulty", 0.0)),
                green_quad=tuple(float(c) for c in h.get("green_quad", [])),
            )
        )
    return holes

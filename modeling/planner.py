"""Whole-hole planner - a 2-D grid MDP (Stage E+).

The single-shot optimiser picks the best *next* shot; this plans the whole hole.
Discretise the hole into a grid of positions; the value of a cell is the expected
strokes to hole out from it under optimal play, and we find it by value iteration:

    V(s) = min over (club, aim) of [ 1 + E_landing V(s') ]

with green cells absorbing into expected putts. The trick that makes it fast: for
a fixed club/lie, the expected value of aiming at *every* cell at once is a single
2-D correlation of the value grid with that shot's landing stencil (its dispersion
as an offset histogram). Aiming = shifting that correlation; the policy is a min
over a few shifted aim choices. So each sweep is a handful of array ops, not a loop
over cells × clubs × samples.

What the action models, so it plays like golf rather than a robot:
  - the *lie* you play from - a full shot from rough/sand carries shorter and
    scatters wider (per-lie stencil + stock), so the fairway is worth aiming at;
  - the player's *one stock shape* - a draw (or fade) bends every shot the same way
    and skews the bad miss; the planner aims that shape, it doesn't flip per shot,
    because real golfers don't move the ball both ways off the tee;
  - elevation makes the carry vary by terrain; the *driver is tee-only*.

Shots are still treated as predominantly downrange (the stencil is axis-aligned),
which is the remaining modelling approximation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from .bag import ClubBag
from .course import CourseHole, Hole
from .scoring import GREEN, RECOVERY, ROUGH, SAND, expected_strokes_array

_LOST = 8.0  # cost charged to a ball that leaves the grid (lost / OB-ish)
_UNREACHABLE = 50.0  # high finite cap for cells with no short-game / no reachable path
# Aim search per club. Downrange tunes distance; the lateral band is graduated and
# wide so the planner can aim around a dogleg corner (tens of yards off the straight
# tee->pin line), while staying fine near centre for ordinary aiming. A wide miss just
# lands in recovery/off-grid and scores worse, so the extra aims never hurt straight holes.
_AIM_SHORT, _AIM_LONG = 30.0, 12.0
_AIM_LATS = (-130.0, -85.0, -52.0, -28.0, -12.0, 0.0, 12.0, 28.0, 52.0, 85.0, 130.0)

# A full shot played *from* a lie: (carry multiplier, dispersion multiplier). Rough
# costs distance and control; sand more so; recovery (trees/junk) most of all - you
# punch out short and wide; everything else plays clean. This is what makes the
# fairway worth aiming at - without it a shot flies identically from fairway or rough,
# so the planner never favours the short grass and just tracks the straight tee->pin
# line. With it, the planner aims at the fat side, lays up to good positions, won't
# bomb driver from a bad lie, and routes around a corner rather than through the trees.
_LIE_MULT = {ROUGH: (0.90, 1.6), SAND: (0.70, 2.3), RECOVERY: (0.45, 2.8)}
_CLEAN, _ROUGH, _SAND, _RECOVERY = 0, 1, 2, 3  # lie-class indices

# A player's *stock* shape is the lateral skew of their dispersion: a draw leaks its
# bad miss one way, a fade the other (signs are for a right-hander; flip for a lefty).
# It's a property of the golfer, not a per-shot choice - they aim their one shape.
SHAPE_SKEW = {"draw": -0.35, "straight": 0.0, "fade": 0.35}

# Carry change per yard of elevation to the landing (validated against the physics:
# all clubs descend ~47deg, so one factor fits the bag). Uphill ground catches the
# ball earlier -> shorter carry; downhill -> longer. ~the golfer's 1-yard-per-yard.
_ELEV_CARRY = 0.93


@dataclass(frozen=True)
class HoleGrid:
    """A hole discretised into cells: positions, lies, and the key indices."""

    cell_size: float
    xs: np.ndarray  # (nx,) downrange centres (yards from the tee)
    ys: np.ndarray  # (ny,) lateral centres (+ = right)
    remaining: np.ndarray  # (nx, ny) distance to the pin
    lie: np.ndarray  # (nx, ny) lie at each cell
    green_mask: np.ndarray  # (nx, ny) bool
    water_mask: np.ndarray  # (nx, ny) bool
    tee_idx: tuple[int, int]
    drop_idx: tuple[int, int]

    @property
    def shape(self) -> tuple[int, int]:
        return self.remaining.shape

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        i = int(np.clip(np.searchsorted(self.xs, x), 0, len(self.xs) - 1))
        j = int(np.clip(np.searchsorted(self.ys, y), 0, len(self.ys) - 1))
        return i, j

    @classmethod
    def build(cls, hole: Hole | CourseHole, cell_size: float) -> HoleGrid:
        x_min, x_max, y_min, y_max = hole.bounds()
        xs = np.arange(x_min + cell_size / 2, x_max, cell_size)
        ys = np.arange(y_min + cell_size / 2, y_max, cell_size)
        gx, gy = np.meshgrid(xs, ys, indexing="ij")
        remaining = hole.remaining_yards(gx, gy)
        lie = hole.lie_at(gx, gy)
        green = lie == GREEN  # the green is wherever the lie says so (radius or polygon)
        water = hole.in_penalty(gx, gy)
        tee = (int(np.argmin(np.abs(xs))), int(np.argmin(np.abs(ys))))
        # Drop just short of the first penalty hazard (else ~30 yds short of the pin).
        drop_x = hole.penalty_drop_x()
        if drop_x is None:
            drop_x = hole.pin_distance_yards - 30.0
        drop = (int(np.clip(np.searchsorted(xs, drop_x), 0, len(xs) - 1)), tee[1])
        return cls(cell_size, xs, ys, remaining, lie, green, water, tee, drop)


def _stencil(stats, cell_size: float, spread: float = 1.0, skew: float = 0.0) -> np.ndarray:
    """A club's landing distribution as a normalised (carry, lateral) offset grid.

    `spread` widens the residual scatter (a shot from rough/sand is less
    predictable). `skew` shapes the shot: a fade (skew > 0) leaks its bad miss
    right, a draw (skew < 0) left - heavier tail on the shaped side, recentred so
    the aim stays the mean. That lets the planner pick a shape whose stray shots
    fall away from the trouble (water, a bunker), the way a golfer actually plays.
    """
    carry = stats.dispersion.landings_carry
    lateral = stats.dispersion.landings_lateral
    carry_resid = carry - carry.mean()
    lat_resid = lateral - lateral.mean()
    if skew:
        lat_resid = lat_resid * (1.0 + skew * np.sign(lat_resid))
        lat_resid = lat_resid - lat_resid.mean()  # recentre: aim is still the mean
    di = np.rint(carry_resid * spread / cell_size).astype(int)
    dj = np.rint(lat_resid * spread / cell_size).astype(int)
    ri = min(int(np.abs(di).max()) + 1, 25)
    rj = min(int(np.abs(dj).max()) + 1, 25)
    k = np.zeros((2 * ri + 1, 2 * rj + 1))
    np.add.at(k, (np.clip(di + ri, 0, 2 * ri), np.clip(dj + rj, 0, 2 * rj)), 1.0)
    return k / k.sum()


def _shift(q: np.ndarray, oi, oj: int, fill: float) -> np.ndarray:
    """`r[i,j] = q[i+oi, j+oj]`, out-of-bounds filled with `fill`.

    `oi` is the downrange offset: a scalar (flat ground) or a per-row `(nx,)` array
    (elevation makes the effective carry vary by where you stand). The scalar path
    is a fast slice; a constant array collapses to it, so flat holes pay nothing.
    """
    nx, ny = q.shape
    if not np.isscalar(oi):
        oi = np.asarray(oi)
        if np.ptp(oi) == 0:  # constant -> fast scalar path
            oi = int(oi.flat[0])
    if np.isscalar(oi):
        r = np.full_like(q, fill)
        i0, i1 = max(0, -oi), min(nx, nx - oi)
        j0, j1 = max(0, -oj), min(ny, ny - oj)
        if i0 < i1 and j0 < j1:
            r[i0:i1, j0:j1] = q[i0 + oi : i1 + oi, j0 + oj : j1 + oj]
        return r
    rows = np.arange(nx) + oi  # (nx,) per-row source
    cols = np.arange(ny) + oj
    rv, cv = (rows >= 0) & (rows < nx), (cols >= 0) & (cols < ny)
    gathered = q[np.clip(rows, 0, nx - 1)][:, np.clip(cols, 0, ny - 1)]
    return np.where(rv[:, None] & cv[None, :], gathered, fill)


@dataclass(frozen=True)
class PlannedShot:
    club: str
    aim_x: float
    aim_y: float
    from_x: float
    from_y: float
    shape: str = "straight"  # draw / straight / fade - how the ball is worked


@dataclass(frozen=True)
class Plan:
    grid: HoleGrid
    value: np.ndarray  # (nx, ny) expected strokes to hole out
    tee_value: float
    shots: list[PlannedShot]  # the recommended full shots from the tee
    finish_strokes: float  # short game + putts to hole out from the last landing


def plan_hole(
    hole: Hole | CourseHole,
    bag: ClubBag,
    *,
    cell_size: float = 4.0,
    tol: float = 1e-3,
    tee_xy: tuple[float, float] | None = None,
    skew: float = 0.0,
    shape: str = "straight",
    short_game: float = 0.0,
) -> Plan:
    """Value-iterate the hole and roll out the recommended shot sequence.

    `tee_xy` is where the player tees off (downrange, lateral); a forward tee sits
    further downrange and plays shorter. Value iteration is the same for every cell,
    so the tee only picks the start of the rollout and where the driver is legal.
    `skew`/`shape` are the player's *stock* shot shape - the same lateral skew on
    every shot (a golfer aims their one shape, they don't pick draw or fade per shot).
    `short_game` is the player's around-and-on-the-green skill (0 = tour): a weaker
    short game raises the floor, so getting up and down is dearer and the plan values
    finding the green over scrambling for it.
    """
    grid = HoleGrid.build(hole, cell_size)
    start = grid.cell_of(*tee_xy) if tee_xy is not None else grid.tee_idx
    penalty = hole.penalty_cost()
    # The short game the bag's full-swing clubs can't model: inside the shortest
    # club's range the player can always hole out in the benchmark expected strokes
    # (a chip/pitch-and-putt). That's a floor V never exceeds, so a ball short of
    # the green isn't "lost". Beyond that range there is no short-game option -
    # only the MDP's full shots - so the floor is lifted (a wedge can't fly 200).
    short_range = min(cs.measured_carry_mean for cs in bag.clubs)
    floor = np.where(
        grid.remaining <= short_range,
        expected_strokes_array(
            grid.remaining,
            grid.lie,
            short_game=short_game,
            green_difficulty=getattr(hole, "green_difficulty", 0.0),
        ),
        _UNREACHABLE,  # no short-game option beyond the shortest club; MDP only
    )

    names = [cs.dispersion.club for cs in bag.clubs]
    # Per club, a stencil + stock for each lie class. A shot from rough or sand
    # carries shorter (smaller stock) and scatters wider. The player's *one* stock
    # shape (skew) bends every shot the same way - real golfers don't flip draw and
    # fade from shot to shot, so the planner aims that shape, it doesn't choose it.
    mults = [(1.0, 1.0), _LIE_MULT[ROUGH], _LIE_MULT[SAND], _LIE_MULT[RECOVERY]]
    kernels = [[_stencil(cs, cell_size, spread, skew) for _d, spread in mults] for cs in bag.clubs]
    stocks = [
        [int(round(cs.measured_carry_mean * dist / cell_size)) for dist, _s in mults]
        for cs in bag.clubs
    ]
    # Elevation turns each flat stock into a per-row field: from a given cell, a shot
    # landing uphill carries shorter (fewer cells), downhill further. _shift takes a
    # per-row offset; a flat hole gives a constant field and the fast scalar path.
    elev = hole.elevation_at(grid.xs)  # (nx,) yards vs tee at each downrange
    _rows = np.arange(grid.shape[0])

    def _stock_field(stock: int) -> np.ndarray:
        landing = np.clip(_rows + stock, 0, grid.shape[0] - 1)
        return stock - np.rint(_ELEV_CARRY * (elev[landing] - elev) / cell_size).astype(int)

    stock_fields = [[_stock_field(stocks[ci][k]) for k in range(4)] for ci in range(len(bag.clubs))]
    # The lie class each cell is played *from* (0 clean, 1 rough, 2 sand, 3 recovery).
    cls = np.zeros(grid.shape, dtype=int)
    cls[grid.lie == ROUGH] = _ROUGH
    cls[grid.lie == SAND] = _SAND
    cls[grid.lie == RECOVERY] = _RECOVERY
    has_rough = bool((cls == _ROUGH).any())
    has_sand = bool((cls == _SAND).any())
    has_recovery = bool((cls == _RECOVERY).any())
    # The driver is legal only off the tee - nobody bombs it off the deck at a
    # guarded green, so off the tee row the planner lays up with a wood/iron.
    is_driver = [n == "Driver" for n in names]
    off_tee = np.ones(grid.shape, dtype=bool)
    off_tee[start[0]] = False  # driver legal only on the tee row you play from
    dds = np.unique(np.rint(np.linspace(-_AIM_SHORT, _AIM_LONG, 8) / cell_size).astype(int))
    dls = np.unique(np.rint(np.array(_AIM_LATS) / cell_size).astype(int))

    def best_actions(v: np.ndarray, track: bool):
        """One Bellman backup: min over (club, aim) of expected strokes.

        Each cell plays the stencil/stock for *its* lie, so a cell in the rough
        evaluates a shorter, looser shot than one in the fairway. The player's stock
        shape is baked into every stencil, so they aim it, not choose it per shot.
        """
        vcost = v.copy()
        vcost[grid.water_mask] = penalty + v[grid.drop_idx]
        best = np.full(grid.shape, np.inf)
        pc = np.full(grid.shape, -1, dtype=int)
        pr = np.zeros(grid.shape, dtype=int)
        pl = np.zeros(grid.shape, dtype=int)
        for ci in range(len(names)):
            qk = [
                1.0 + ndimage.correlate(vcost, kernels[ci][k], mode="constant", cval=_LOST)
                for k in range(4)
            ]
            sf = stock_fields[ci]
            for dd in dds:
                for dl in dls:
                    # Default everyone to the clean shot, then override rough / sand
                    # cells with their own (shorter, wider) shot. The stock is a
                    # per-row field (elevation), so `off` varies by row.
                    cand = _shift(qk[_CLEAN], sf[_CLEAN] + dd, dl, _LOST)
                    off = np.broadcast_to((sf[_CLEAN] + dd)[:, None], grid.shape)
                    if has_rough:
                        m = cls == _ROUGH
                        cand = np.where(m, _shift(qk[_ROUGH], sf[_ROUGH] + dd, dl, _LOST), cand)
                        off = np.where(m, (sf[_ROUGH] + dd)[:, None], off)
                    if has_sand:
                        m = cls == _SAND
                        cand = np.where(m, _shift(qk[_SAND], sf[_SAND] + dd, dl, _LOST), cand)
                        off = np.where(m, (sf[_SAND] + dd)[:, None], off)
                    if has_recovery:
                        m = cls == _RECOVERY
                        cand = np.where(
                            m, _shift(qk[_RECOVERY], sf[_RECOVERY] + dd, dl, _LOST), cand
                        )
                        off = np.where(m, (sf[_RECOVERY] + dd)[:, None], off)
                    if is_driver[ci]:
                        cand = np.where(off_tee, np.inf, cand)  # driver only off the tee
                    take = cand < best
                    best = np.where(take, cand, best)
                    if track:
                        pc = np.where(take, ci, pc)
                        pr = np.where(take, off, pr)
                        pl = np.where(take, dl, pl)
        return best, pc, pr, pl

    v = floor.copy()
    for _ in range(300):
        best, *_ = best_actions(v, track=False)
        vnew = np.minimum(floor, best)  # the short-game floor caps every cell
        delta = float(np.max(np.abs(vnew - v)))
        v = vnew
        if delta < tol:
            break

    best_final, pc, pr, pl = best_actions(v, track=True)
    # Stop the rollout once on the green or where the short-game floor already
    # beats any full shot - from there you chip and putt, scored by the floor.
    reached = grid.green_mask | (best_final >= floor - 1e-9)
    shots = _rollout(grid, names, pc, pr, pl, reached, start=start, shape=shape)
    last = grid.cell_of(shots[-1].aim_x, shots[-1].aim_y) if shots else start
    return Plan(
        grid=grid,
        value=v,
        tee_value=float(v[start]),
        shots=shots,
        finish_strokes=float(v[last]),
    )


def _rollout(grid, names, pc, pr, pl, green, *, start=None, shape="straight", max_shots: int = 10):
    """Walk the policy from the tee, taking the expected landing each shot."""
    s = start if start is not None else grid.tee_idx
    shots: list[PlannedShot] = []
    while not green[s] and len(shots) < max_shots and pc[s] >= 0:
        ai = int(np.clip(s[0] + pr[s], 0, grid.shape[0] - 1))
        aj = int(np.clip(s[1] + pl[s], 0, grid.shape[1] - 1))
        shots.append(
            PlannedShot(
                club=names[pc[s]],
                aim_x=float(grid.xs[ai]),
                aim_y=float(grid.ys[aj]),
                from_x=float(grid.xs[s[0]]),
                from_y=float(grid.ys[s[1]]),
                shape=shape,
            )
        )
        if (ai, aj) == s:
            break
        s = (ai, aj)
    return shots

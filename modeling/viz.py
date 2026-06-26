"""Trajectory and dispersion visualization (Stage F, first pieces).

Renders a single simulated shot two ways - side-on (carry vs height) and
top-down (downrange vs lateral) - and a club's Monte-Carlo dispersion as a
top-down landing chart, so the physics is visible, not just numeric. Uses a
non-interactive backend so it works headless / in CI.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless: render to file, no display needed
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Circle, Ellipse, PathPatch, Rectangle  # noqa: E402
from matplotlib.path import Path as MplPath  # noqa: E402

from .contracts import M_TO_YARDS  # noqa: E402
from .course import SAND, CourseHole, Hole  # noqa: E402
from .dispersion import ClubDispersion  # noqa: E402
from .physics import Trajectory  # noqa: E402

# shared yardage-book palette, matching the caddie renders for one consistent look
_BG = "#f5f3ea"
_INK = "#33312c"
_FAIRWAY = "#bcdc8c"
_GREEN = "#57a957"
_SAND = "#ecdca4"
_WATER = "#84bfe6"
_PLAY = "#c0392b"

# hazard fill colours by kind
_HAZARD_COLORS = {"water": _WATER, "ob": "#cfccbe", SAND: _SAND}

# distinct, colourblind-friendly hues cycled across clubs in the dispersion plot
_CLUB_COLORS = ["#1e40af", "#166534", "#b45309", "#9333ea", "#be123c", "#0e7490"]


# one paper-book look for every engine plot, matching the caddie renders
plt.rcParams.update(
    {
        "figure.facecolor": _BG,
        "axes.facecolor": _BG,
        "savefig.facecolor": _BG,
        "axes.edgecolor": "#cfccbe",
        "axes.titleweight": "bold",
        "axes.titlecolor": _INK,
        "axes.labelcolor": "#6c6a62",
        "xtick.color": "#8a887e",
        "ytick.color": "#8a887e",
        "axes.grid": True,
        "grid.color": "#e3e0d4",
    }
)


def plot_trajectory(traj: Trajectory, title: str, out_path: str) -> str:
    """Render a trajectory (side + top-down) to a PNG. Returns the path."""
    pts = traj.points
    downrange = pts[:, 0] * M_TO_YARDS
    lateral = pts[:, 1] * M_TO_YARDS
    height = pts[:, 2] * M_TO_YARDS

    fig, (side, top) = plt.subplots(2, 1, figsize=(9, 7))

    side.plot(downrange, height, color="#1e40af")
    side.fill_between(downrange, 0, height, color="#dbeafe")
    side.set_title(f"{title} - side view")
    side.set_xlabel("downrange (yds)")
    side.set_ylabel("height (yds)")
    side.set_aspect("equal", adjustable="box")
    side.grid(True, alpha=0.3)

    top.plot(downrange, lateral, color="#166534")
    top.axhline(0, color="#9ca3af", lw=0.8, ls="--")  # target line
    top.set_title("top-down (curve)")
    top.set_xlabel("downrange (yds)")
    top.set_ylabel("lateral (+ right, yds)")
    top.grid(True, alpha=0.3)

    fig.suptitle(
        f"carry {traj.carry_yards:.1f} yds · peak {traj.peak_height_yards:.1f} yds · "
        f"lateral {traj.lateral_yards:+.1f} yds · descent {traj.descent_angle_deg:.1f}°",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


def _one_sigma_ellipse(lateral: np.ndarray, carry: np.ndarray, color: str) -> Ellipse:
    """A 1-sigma confidence ellipse for a landing cloud, in plot coords (x = lateral)."""
    cov = np.cov(np.vstack([lateral, carry]))
    vals, vecs = np.linalg.eigh(cov)
    order = vals.argsort()[::-1]
    vals, vecs = np.clip(vals[order], 0.0, None), vecs[:, order]
    angle = float(np.degrees(np.arctan2(vecs[1, 0], vecs[0, 0])))
    width, height = 2.0 * np.sqrt(vals)  # 1-sigma diameters along the principal axes
    return Ellipse(
        (float(lateral.mean()), float(carry.mean())),
        width=float(width),
        height=float(height),
        angle=angle,
        facecolor=color,
        edgecolor=color,
        alpha=0.18,
        lw=1.6,
    )


def plot_dispersion(dispersions: list[ClubDispersion], title: str, out_path: str) -> str:
    """Top-down landing chart: per-club scatter + 1-sigma ellipse. Returns the path."""
    fig, ax = plt.subplots(figsize=(8, 9))

    all_carry, all_lateral = [], []
    for i, d in enumerate(dispersions):
        color = _CLUB_COLORS[i % len(_CLUB_COLORS)]
        lat, carry = d.landings_lateral, d.landings_carry
        all_carry.append(carry)
        all_lateral.append(lat)
        ax.scatter(lat, carry, s=4, alpha=0.08, color=color, edgecolors="none")
        ax.add_patch(_one_sigma_ellipse(lat, carry, color))
        ax.scatter(
            [d.lateral_mean_yards],
            [d.carry_mean_yards],
            s=22,
            color=color,
            zorder=5,
            label=f"{d.club} · {d.carry_mean_yards:.0f}±{d.carry_std_yards:.0f} yds",
        )

    # Bound the view to the meaningful region - Gaussian tails throw a few wild
    # samples that would otherwise blow out the axes.
    carry_cat = np.concatenate(all_carry)
    lateral_cat = np.concatenate(all_lateral)
    lat_lim = float(np.percentile(np.abs(lateral_cat), 99)) * 1.1
    ax.set_xlim(-lat_lim, lat_lim)
    ax.set_ylim(0, float(np.percentile(carry_cat, 99)) * 1.1)

    ax.axvline(0, color="#9ca3af", lw=0.8, ls="--")  # target line
    ax.set_xlabel("lateral (+ right, yds)")
    ax.set_ylabel("carry (yds)")
    ax.set_title(title)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)

    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


def plot_scoring(rows: list[tuple[str, float, float]], title: str, out_path: str) -> str:
    """Bar chart of expected strokes to hole out, your dispersion vs a benchmark.

    `rows` is (club, your_expected_strokes, benchmark_expected_strokes), longest
    club first. The gap between the bars is the strokes a tighter distance
    control would save from that club's stock distance.
    """
    clubs = [r[0] for r in rows]
    yours = np.array([r[1] for r in rows])
    bench = np.array([r[2] for r in rows])
    x = np.arange(len(clubs))

    fig, ax = plt.subplots(figsize=(max(7, len(clubs) * 1.3), 5))
    ax.bar(x - 0.2, yours, width=0.4, color="#be123c", label="your dispersion")
    ax.bar(x + 0.2, bench, width=0.4, color="#166534", label="tight benchmark")
    for xi, (y, b) in enumerate(zip(yours, bench, strict=True)):
        ax.annotate(
            f"+{y - b:.2f}",
            (xi, y),
            textcoords="offset points",
            xytext=(0, 3),
            ha="center",
            fontsize=8,
            color="#be123c",
        )

    ax.set_xticks(x)
    ax.set_xticklabels(clubs, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("expected strokes to hole out")
    ax.set_ylim(bottom=min(2.0, float(bench.min()) - 0.1))
    ax.set_title(title)
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


def plot_benchmark(
    clubs: list[str],
    published: np.ndarray,
    simulated: np.ndarray,
    title: str,
    out_path: str,
) -> str:
    """Grouped bars of published vs engine-simulated carry per club. Returns the path."""
    x = np.arange(len(clubs))
    fig, ax = plt.subplots(figsize=(max(8, len(clubs) * 0.95), 5))
    ax.bar(x - 0.2, published, width=0.4, color="#166534", label="TrackMan published")
    ax.bar(x + 0.2, simulated, width=0.4, color="#1e40af", label="engine simulated")
    for xi, (p, s) in enumerate(zip(published, simulated, strict=True)):
        ax.annotate(
            f"{s - p:+.0f}",
            (xi, max(p, s)),
            textcoords="offset points",
            xytext=(0, 3),
            ha="center",
            fontsize=7,
            color="#1e40af",
        )

    ax.set_xticks(x)
    ax.set_xticklabels(clubs, rotation=40, ha="right", fontsize=8)
    ax.set_ylabel("carry (yds)")
    ax.set_title(title)
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


def plot_hole(
    hole: Hole,
    carry: np.ndarray,
    lateral: np.ndarray,
    best,
    title: str,
    out_path: str,
) -> str:
    """Top-down hole view: green, fairway, hazards, the landing cloud and the aim.

    `carry`/`lateral` are the recommended club's landing cloud at the optimal aim;
    `best` is its ShotChoice. x is lateral (+ right), y is downrange to the pin.
    """
    pin = hole.pin_distance_yards
    y_top = max(pin + 25.0, float(np.percentile(carry, 99)))
    fw = hole.fairway_half_width_yards

    fig, ax = plt.subplots(figsize=(7, 9))
    # Fairway corridor, then green, then hazards on top.
    ax.add_patch(
        Rectangle((-fw, 0.0), 2 * fw, y_top, facecolor=_FAIRWAY, edgecolor="none", zorder=0)
    )
    ax.add_patch(
        Circle((0.0, pin), hole.green_radius_yards, facecolor=_GREEN, edgecolor="none", zorder=1)
    )
    for hz in hole.hazards:
        r = hz.region
        ax.add_patch(
            Rectangle(
                (r.left, r.near),
                r.right - r.left,
                r.far - r.near,
                facecolor=_HAZARD_COLORS.get(hz.kind, "#d1d5db"),
                edgecolor="none",
                alpha=0.9,
                zorder=2,
            )
        )

    ax.scatter(lateral, carry, s=4, alpha=0.12, color="#1e3a8a", edgecolors="none", zorder=3)
    ax.scatter([0.0], [pin], marker="*", s=180, color=_PLAY, zorder=5, label="pin")
    ax.scatter(
        [best.aim_lateral_yards],
        [best.aim_distance_yards],
        marker="+",
        s=160,
        color="#111827",
        linewidths=2,
        zorder=6,
        label="optimiser aim",
    )

    ax.axvline(0.0, color="#9ca3af", lw=0.7, ls="--", zorder=1)
    ax.set_xlabel("lateral (+ right, yds)")
    ax.set_ylabel("downrange to pin (yds)")
    ax.set_title(title)
    ax.set_aspect("equal", adjustable="box")
    ax.set_ylim(0, y_top)
    ax.legend(loc="lower right", fontsize=8, framealpha=0.9)

    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


def _poly_patch(poly, **kwargs) -> PathPatch:
    """A matplotlib patch for a shapely Polygon, swapping (downrange, lateral) ->
    plot (lateral, downrange) and honouring interior holes via the even-odd rule."""

    def ring(coords) -> tuple[list, list]:
        verts = [(p[1], p[0]) for p in coords]  # swap to (lateral, downrange)
        codes = [MplPath.MOVETO] + [MplPath.LINETO] * (len(verts) - 2) + [MplPath.CLOSEPOLY]
        return verts, codes

    verts, codes = ring(poly.exterior.coords)
    for interior in poly.interiors:
        iv, ic = ring(interior.coords)
        verts += iv
        codes += ic
    return PathPatch(MplPath(verts, codes), **kwargs)


def _draw_geom(ax, geom, **kwargs) -> None:
    """Draw a shapely (Multi)Polygon as filled patches (no-op if empty)."""
    if geom is None or geom.is_empty:
        return
    parts = getattr(geom, "geoms", [geom])
    for part in parts:
        if part.geom_type == "Polygon":
            ax.add_patch(_poly_patch(part, **kwargs))


def _shaped_curve(from_x, from_y, aim_x, aim_y, bend_dir: float):
    """A quadratic-bezier flight path that bulges laterally by `bend_dir` (+1 the
    ball works right-to-left, -1 left-to-right, 0 straight), in (lateral, downrange)."""
    t = np.linspace(0.0, 1.0, 24)
    bend = bend_dir * min(0.05 * abs(aim_x - from_x), 12.0)
    cx = (from_x + aim_x) / 2  # control point: midpoint, pushed sideways by the bend
    cy = (from_y + aim_y) / 2 + bend
    downrange = (1 - t) ** 2 * from_x + 2 * (1 - t) * t * cx + t**2 * aim_x
    lateral = (1 - t) ** 2 * from_y + 2 * (1 - t) * t * cy + t**2 * aim_y
    return lateral, downrange


def plot_course_plan(
    hole: CourseHole, plan, bag, title: str, out_path: str, skew: float = 0.0
) -> str:
    """Top-down real hole (OSM outlines) with the strategy heatmap and shot path.

    Draws the actual green / fairway / bunker / water polygons, a faint
    expected-strokes underlay, and the recommended tee-to-green sequence as curved,
    shaped flights with each landing's 1-sigma dispersion ellipse - so the scatter
    and shot shape are visible, not a straight line. x is lateral (+ right), y is
    downrange to the pin.
    """
    x_min, x_max, y_min, y_max = hole.bounds()
    xs, ys, value, shots = plan.grid.xs, plan.grid.ys, plan.value, plan.shots
    fig, ax = plt.subplots(figsize=(7, 10))

    # Rough fills the frame; the value heatmap tints it (danger = red); real
    # green/fairway/bunker/water polygons sit on top.
    ax.add_patch(
        Rectangle(
            (y_min, x_min), y_max - y_min, x_max - x_min, facecolor="#d6e3b1", edgecolor="none"
        )
    )
    ax.imshow(
        np.clip(value, 0, 6),
        origin="lower",
        extent=[ys[0], ys[-1], xs[0], xs[-1]],
        aspect="equal",
        cmap="RdYlGn_r",
        alpha=0.28,
        zorder=1,
    )
    _draw_geom(ax, hole.fairway, facecolor=_FAIRWAY, edgecolor="#16a34a", lw=0.8, zorder=2)
    _draw_geom(ax, hole.green, facecolor=_GREEN, edgecolor="#065f46", lw=1.2, zorder=3)
    _draw_geom(ax, hole.bunkers, facecolor=_SAND, edgecolor="#d97706", lw=0.6, zorder=4)
    _draw_geom(ax, hole.water, facecolor="#7dd3fc", edgecolor="#0369a1", lw=0.8, zorder=4)

    # Tee -> each landing -> green: a curved, shaped flight per shot, with the
    # club's 1-sigma landing ellipse so the dispersion is visible. Every shot bends
    # the same way - the player's one stock shape.
    bend_dir = 0.0 if abs(skew) < 1e-6 else (-1.0 if skew > 0 else 1.0)
    disp_by_club = {cs.dispersion.club: cs.dispersion for cs in bag.clubs}
    for s in shots:
        lat, dr = _shaped_curve(s.from_x, s.from_y, s.aim_x, s.aim_y, bend_dir)
        ax.plot(lat, dr, color="#111827", lw=1.8, zorder=6)
        d = disp_by_club.get(s.club)
        if d is not None:
            carry = d.landings_carry - d.landings_carry.mean() + s.aim_x
            latc = d.landings_lateral - d.landings_lateral.mean() + s.aim_y
            ax.add_patch(_one_sigma_ellipse(latc, carry, "#1e3a8a"))
        ax.scatter([s.aim_y], [s.aim_x], color="#111827", s=16, zorder=7)
        ax.annotate(
            f"{s.club} · {s.shape}",
            (s.aim_y, s.aim_x),
            textcoords="offset points",
            xytext=(7, -2),
            fontsize=8,
            color="#111827",
            zorder=8,
        )
    ax.scatter([0.0], [0.0], marker="s", s=40, color="#111827", zorder=8)  # tee
    ax.scatter([0.0], [hole.pin_distance_yards], marker="*", s=200, color=_PLAY, zorder=8)
    ax.scatter([0.0], [0.0], marker="s", s=40, color="#111827", zorder=8, label="tee")

    ax.set_xlabel("lateral (+ right, yds)")
    ax.set_ylabel("downrange to pin (yds)")
    ax.set_title(f"{title}\nexpected score {plan.tee_value:.2f}")
    ax.set_xlim(y_min, y_max)
    ax.set_ylim(x_min, x_max)
    ax.set_aspect("equal", adjustable="box")

    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


def plot_aim(hole, bag, pin_xy, advice, title: str, out_path: str) -> str:
    """Zoom on the green: the flag, the recommended aim, and your landing cloud.

    Shows where the strokes-gained-optimal aim sits relative to the pin and the
    trouble around it. x is lateral (+ right), y is downrange.
    """
    pin_x, pin_y = pin_xy
    aim_x, aim_y = pin_x + advice.long_yds, pin_y + advice.right_yds
    d = next(cs.dispersion for cs in bag.clubs if cs.dispersion.club == advice.club)
    carry = d.landings_carry - d.landings_carry.mean() + aim_x
    lat = d.landings_lateral - d.landings_lateral.mean() + aim_y

    gx0, gy0, gx1, gy1 = hole.green.bounds  # (downrange0, lateral0, downrange1, lateral1)
    x_lo = min(gx0, float(carry.min())) - 12
    x_hi = max(gx1, float(carry.max())) + 12
    y_lo = min(gy0, float(lat.min())) - 12
    y_hi = max(gy1, float(lat.max())) + 12

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.add_patch(
        Rectangle((y_lo, x_lo), y_hi - y_lo, x_hi - x_lo, facecolor="#d6e3b1", edgecolor="none")
    )
    _draw_geom(ax, hole.fairway, facecolor=_FAIRWAY, edgecolor="#16a34a", lw=0.8, zorder=1)
    _draw_geom(ax, hole.green, facecolor=_GREEN, edgecolor="#065f46", lw=1.2, zorder=2)
    _draw_geom(ax, hole.bunkers, facecolor=_SAND, edgecolor="#d97706", lw=0.6, zorder=3)
    _draw_geom(ax, hole.water, facecolor="#7dd3fc", edgecolor="#0369a1", lw=0.8, zorder=3)
    ax.scatter(lat, carry, s=6, alpha=0.12, color="#1e3a8a", edgecolors="none", zorder=4)
    ax.add_patch(_one_sigma_ellipse(lat, carry, "#1e3a8a"))
    # Fall line: an arrow from the green centre pointing downhill (where it drains).
    a, b = getattr(hole, "green_slope", (0.0, 0.0))
    mag = (a * a + b * b) ** 0.5
    if mag > 1e-4:
        cen = hole.green.centroid
        L = 0.4 * min(gx1 - gx0, gy1 - gy0)  # arrow length ~ green size
        ax.annotate(
            "",
            xy=(cen.y - b / mag * L, cen.x - a / mag * L),
            xytext=(cen.y, cen.x),
            arrowprops={"arrowstyle": "-|>", "color": "#7c2d12", "lw": 2.2},
            zorder=5,
        )
        ax.text(cen.y, cen.x, f"  falls {mag * 100:.0f}%", color="#7c2d12", fontsize=8, zorder=7)
    ax.plot([aim_y, pin_y], [aim_x, pin_x], color="#111827", lw=1.2, ls="--", zorder=5)
    ax.scatter([pin_y], [pin_x], marker="*", s=240, color=_PLAY, zorder=6, label="flag")
    ax.scatter(
        [aim_y], [aim_x], marker="+", s=180, color="#111827", linewidths=2.5, zorder=6, label="aim"
    )
    ax.set_xlabel("lateral (+ right, yds)")
    ax.set_ylabel("downrange (yds)")
    ax.set_title(title)
    ax.set_xlim(y_lo, y_hi)
    ax.set_ylim(x_lo, x_hi)
    ax.set_aspect("equal", adjustable="box")
    ax.legend(loc="lower right", fontsize=8, framealpha=0.9)

    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


def plot_plan(hole, xs, ys, value, shots, title: str, out_path: str) -> str:
    """Top-down hole with the value heatmap and the recommended shot path.

    `value` is the (nx, ny) expected-strokes grid over (downrange xs, lateral ys);
    `shots` is the rollout (each with from_x/from_y/aim_x/aim_y/club). x is lateral
    (+ right), y is downrange to the pin.
    """
    pin = hole.pin_distance_yards
    fw = hole.fairway_half_width_yards
    fig, ax = plt.subplots(figsize=(7, 9))

    vis = np.clip(value, 0, 6)  # cap so the heatmap stays readable
    ax.imshow(
        vis,
        origin="lower",
        extent=[ys[0], ys[-1], xs[0], xs[-1]],
        aspect="equal",
        cmap="RdYlGn_r",
        alpha=0.85,
    )
    ax.axvline(0.0, color="#9ca3af", lw=0.6, ls="--", zorder=1)
    ax.plot([-fw, -fw], [0, xs[-1]], color="#16a34a", lw=0.8, alpha=0.5)
    ax.plot([fw, fw], [0, xs[-1]], color="#16a34a", lw=0.8, alpha=0.5)
    ax.add_patch(
        Circle((0.0, pin), hole.green_radius_yards, facecolor="none", edgecolor="#065f46", lw=2)
    )
    for hz in hole.hazards:
        r = hz.region
        ax.add_patch(
            Rectangle(
                (r.left, r.near),
                r.right - r.left,
                r.far - r.near,
                facecolor=_HAZARD_COLORS.get(hz.kind, "#d1d5db"),
                edgecolor="none",
                alpha=0.85,
                zorder=2,
            )
        )

    # The recommended shot path: tee -> each landing -> ... and the clubs.
    px, py = [0.0], [0.0]
    for s in shots:
        px.append(s.aim_y)
        py.append(s.aim_x)
    ax.plot(px, py, "-o", color="#111827", lw=1.8, ms=5, zorder=5)
    for s in shots:
        ax.annotate(
            s.club,
            (s.aim_y, s.aim_x),
            textcoords="offset points",
            xytext=(6, -2),
            fontsize=8,
            color="#111827",
        )
    ax.scatter([0.0], [pin], marker="*", s=180, color=_PLAY, zorder=6)

    ax.set_xlabel("lateral (+ right, yds)")
    ax.set_ylabel("downrange to pin (yds)")
    ax.set_title(title)
    ax.set_xlim(ys[0], ys[-1])
    ax.set_ylim(0, xs[-1])

    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path

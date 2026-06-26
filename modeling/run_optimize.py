"""Recommend a shot on a real 2-D hole, from real gold data (Stage E).

Builds a hole scaled to the player's bag - a green guarded by a pond front-right
and a bunker left - and asks the optimiser which club and aim point (downrange
*and* lateral) minimise expected strokes to hole out. It prints the ranked
options, contrasts the pick with naively firing at the flag, and renders the hole
with the recommended club's landing cloud.

Run via `just optimize`. Needs the `modeling` group and BigQuery ADC. Uses both
validated dimensions now - carry spread and lateral spread.
"""

from __future__ import annotations

import os
import sys

import numpy as np

from .course import SAND, WATER, Hazard, Hole, Region
from .optimize import evaluate_shot, optimize_shot
from .synthetic import resolve_bag
from .viz import plot_hole


def main() -> None:
    # Optional CLI skill (tour/scratch/amateur) -> a clean synthetic bag; else real.
    skill = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None
    bag = resolve_bag(skill)
    clubs = [
        (
            cs.dispersion.club,
            cs.dispersion.landings_carry
            - cs.dispersion.landings_carry.mean()
            + cs.measured_carry_mean,
            cs.dispersion.landings_lateral,
        )
        for cs in bag.clubs
    ]
    pin = round(float(np.median([c.measured_carry_mean for c in bag.clubs])) + 8)

    hole = Hole(
        pin_distance_yards=pin,
        green_radius_yards=6.0,
        fairway_half_width_yards=16.0,
        hazards=(
            Hazard(Region(near=pin - 26, far=pin - 5, left=3, right=45), kind=WATER),
            Hazard(Region(near=pin - 12, far=pin + 6, left=-32, right=-11), kind=SAND),
        ),
    )
    print(f"player: {bag.player} ({bag.source})")
    print(f"hole: pin {pin} yds, green r=6, pond front-right, bunker left\n")

    ranked = optimize_shot(clubs, hole)
    header = (
        f"{'club':<15}{'aim d':>7}{'aim lat':>8}{'E[str]':>8}{'water%':>8}{'green%':>8}{'prox':>7}"
    )
    print(header)
    print("-" * len(header))
    for c in ranked:
        print(
            f"{c.club:<15}{c.aim_distance_yards:>7.0f}{c.aim_lateral_yards:>+8.0f}"
            f"{c.expected_strokes:>8.2f}{c.penalty_pct * 100:>7.0f}%{c.frac_on_green * 100:>7.0f}%"
            f"{c.mean_proximity_yards:>7.1f}"
        )

    naive_club, naive_c, naive_l = min(clubs, key=lambda kv: abs(kv[1].mean() - pin))
    naive = evaluate_shot(naive_c, naive_l, pin, 0.0, hole)
    best = ranked[0]
    print(
        f"\nnaive: {naive_club} at the flag -> {naive.expected_strokes:.2f} "
        f"({naive.penalty_pct * 100:.0f}% water)"
    )
    saved = naive.expected_strokes - best.expected_strokes
    print(
        f"optimiser: {best.club} aim {best.aim_distance_yards:.0f}yd "
        f"{best.aim_lateral_yards:+.0f} lateral -> {best.expected_strokes:.2f} "
        f"({best.penalty_pct * 100:.0f}% water); saved {saved:+.2f}"
    )

    _, best_c, best_l = next(kv for kv in clubs if kv[0] == best.club)
    carry = best_c - best_c.mean() + best.aim_distance_yards
    lateral = best_l - best_l.mean() + best.aim_lateral_yards
    os.makedirs("modeling/artifacts", exist_ok=True)
    out = plot_hole(
        hole,
        carry,
        lateral,
        best,
        title=f"Shot choice - {best.club} to a {pin}-yd pin ({bag.player})",
        out_path="modeling/artifacts/hole.png",
    )
    print(f"\nhole plotted -> {out}")


if __name__ == "__main__":
    main()

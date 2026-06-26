"""Plan a whole hole and render it (Stage E+ - the MDP planner).

`just plan [skill]` builds a par-4 guarded by water and a bunker, value-iterates
the 2-D grid, and prints the recommended shot sequence + the expected score, then
renders the value heatmap with the recommended path.

Run via `just plan [tour|scratch|amateur]`. Needs the `modeling` group only.
"""

from __future__ import annotations

import os
import sys

from .course import SAND, WATER, Hazard, Hole, Region
from .planner import plan_hole
from .synthetic import skill_from_name, synthetic_bag
from .viz import plot_plan


def main() -> None:
    skill = sys.argv[1] if len(sys.argv) > 1 else "tour"
    bag = synthetic_bag("pga", skill_from_name(skill))

    pin = 420
    hole = Hole(
        pin_distance_yards=pin,
        green_radius_yards=8.0,
        fairway_half_width_yards=18.0,
        hazards=(
            Hazard(Region(near=pin - 25, far=pin - 6, left=4, right=50), kind=WATER),
            Hazard(Region(near=pin - 12, far=pin + 8, left=-34, right=-14), kind=SAND),
        ),
    )
    plan = plan_hole(hole, bag)

    print(f"player: {bag.player}")
    print(f"hole: {pin}-yd par 4, pond front-right, bunker left")
    print(f"expected score (tee value): {plan.tee_value:.2f}\n")
    print(f"{'#':>2}  {'club':<8}{'from':>13}{'aim':>15}")
    print("-" * 40)
    for i, s in enumerate(plan.shots, 1):
        frm = f"({s.from_x:4.0f},{s.from_y:+4.0f})"
        aim = f"({s.aim_x:4.0f},{s.aim_y:+4.0f})"
        print(f"{i:>2}  {s.club:<8}{frm} -> {aim}")
    print(f"    then chip + putt: {plan.finish_strokes:.2f}")

    os.makedirs("modeling/artifacts", exist_ok=True)
    out = plot_plan(
        hole,
        plan.grid.xs,
        plan.grid.ys,
        plan.value,
        plan.shots,
        title=f"Whole-hole plan - {bag.player}\n{pin}-yd par 4, expected {plan.tee_value:.2f}",
        out_path="modeling/artifacts/plan.png",
    )
    print(f"\nplan plotted -> {out}")


if __name__ == "__main__":
    main()

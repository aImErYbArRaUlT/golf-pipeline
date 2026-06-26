"""Plan a hole of a real course and render its outline (the OSM course layer).

`just course [hole] [skill]` loads Torrey Pines South from its committed OSM
geometry, plans the chosen hole with a synthetic bag, prints the recommended
sequence + expected score, and renders the real green/fairway/bunker/water
outlines with the plan drawn on top.

Run via `just course [1-18] [tour|scratch|amateur]`. Needs the `modeling` group.
"""

from __future__ import annotations

import os
import sys

from .course import load_course
from .planner import plan_hole
from .synthetic import skill_from_name, synthetic_bag
from .viz import plot_course_plan


def main() -> None:
    ref = int(sys.argv[1]) if len(sys.argv) > 1 else 18
    skill = sys.argv[2] if len(sys.argv) > 2 else "tour"
    holes = load_course("torrey_pines_south")
    hole = next(h for h in holes if h.ref == ref)
    bag = synthetic_bag("pga", skill_from_name(skill))
    plan = plan_hole(hole, bag, cell_size=5.0)

    print(f"player: {bag.player}")
    print(f"hole: {hole.label}, {hole.pin_distance_yards:.0f} yds")
    print(f"expected score (tee value): {plan.tee_value:.2f}\n")
    print(f"{'#':>2}  {'club':<8}{'from':>13}{'aim':>15}")
    print("-" * 40)
    for i, s in enumerate(plan.shots, 1):
        frm = f"({s.from_x:4.0f},{s.from_y:+4.0f})"
        aim = f"({s.aim_x:4.0f},{s.aim_y:+4.0f})"
        print(f"{i:>2}  {s.club:<8}{frm} -> {aim}")
    print(f"    then chip + putt: {plan.finish_strokes:.2f}")

    os.makedirs("modeling/artifacts", exist_ok=True)
    out = plot_course_plan(
        hole,
        plan,
        bag,
        title=f"{hole.label} - {bag.player}",
        out_path="modeling/artifacts/course.png",
    )
    print(f"\nhole plotted -> {out}")


if __name__ == "__main__":
    main()

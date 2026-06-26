"""Show a synthetic bag's dispersion at a chosen tour + skill level.

`just synth pga scratch` builds a believable bag from TrackMan tour means scattered
to a skill level, and plots the landing ovals - clean demo data, no warehouse.

Run via `just synth [tour] [skill]`. Needs the `modeling` group only.
"""

from __future__ import annotations

import os
import sys

from .synthetic import skill_from_name, synthetic_bag
from .viz import plot_dispersion


def main() -> None:
    tour = sys.argv[1] if len(sys.argv) > 1 else "pga"
    skill_name = sys.argv[2] if len(sys.argv) > 2 else "scratch"
    bag = synthetic_bag(tour, skill_from_name(skill_name))
    print(f"synthetic bag: {bag.player} - {len(bag.clubs)} clubs\n")

    header = f"{'club':<15}{'carry':>14}{'lateral σ':>12}"
    print(header)
    print("-" * len(header))
    for cs in bag.clubs:
        d = cs.dispersion
        carry = f"{d.carry_mean_yards:.0f}±{d.carry_std_yards:.0f}"
        print(f"{d.club:<15}{carry:>14}{d.lateral_std_yards:>12.1f}")

    # Plot a readable spread of up to 6 clubs across the bag.
    stride = max(1, len(bag.clubs) // 6)
    shown = [cs.dispersion for cs in bag.clubs[::stride]][:6]
    os.makedirs("modeling/artifacts", exist_ok=True)
    out = plot_dispersion(
        shown,
        title=f"Synthetic dispersion - {bag.player}\n1-sigma landing ovals",
        out_path="modeling/artifacts/synthetic.png",
    )
    print(f"\ndispersion plotted -> {out}")


if __name__ == "__main__":
    main()

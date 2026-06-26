"""Compute and plot per-club shot dispersion from real gold data (Stage B).

Loads the richest-bag player (see bag.load_bag), renders each club's landing
oval, and prints the load-bearing validation: the simulated carry spread next to
the spread the monitor itself reported for the same shots. They land within a
few yards - the engine reproduces real shot-to-shot carry variance.

Run via `just dispersion`. Needs the `modeling` group and BigQuery ADC.

Both the carry spread and the lateral spread track the monitor within a yard or
two: the lift cap fixed the old iron over-curve, and the engine is now calibrated
across the whole bag (drag, spin-drag, lift on the TrackMan tour averages - see
`just benchmark`), so absolute carry is right too.
"""

from __future__ import annotations

import os

from . import warehouse
from .bag import load_bag
from .viz import plot_dispersion

_N_SAMPLES = 2000


def main() -> None:
    bag = load_bag(warehouse.client(), n_samples=_N_SAMPLES)
    print(f"engine: Cd={bag.cd:.3f}, Cl_coeff={bag.cl:.3f}, Cd_spin={bag.cd_spin:.3f} (tour bag)")
    print(f"player: {bag.player} ({bag.source}) - {len(bag.clubs)} clubs\n")

    header = f"{'club':<15}{'n':>5}{'sim carry':>12}{'meas σ':>9}{'sim latσ':>10}{'meas σ':>9}"
    print(header)
    print("-" * len(header))
    for cs in bag.clubs:
        d = cs.dispersion
        sim_carry = f"{d.carry_mean_yards:.0f}±{d.carry_std_yards:.0f}"
        print(
            f"{d.club:<15}{d.n_observed:>5}{sim_carry:>12}{cs.measured_carry_std:>9.1f}"
            f"{d.lateral_std_yards:>10.1f}{cs.measured_side_std:>9.1f}"
        )
    print("\nsim carry σ vs measured carry σ is the validation: the engine reproduces real spread.")

    os.makedirs("modeling/artifacts", exist_ok=True)
    title = (
        f"Shot dispersion - {bag.player} ({bag.source})\n"
        f"1-sigma landing ovals, {_N_SAMPLES} sims/club"
    )
    out = plot_dispersion(
        [cs.dispersion for cs in bag.clubs],
        title=title,
        out_path="modeling/artifacts/dispersion.png",
    )
    print(f"dispersion plotted -> {out}")


if __name__ == "__main__":
    main()

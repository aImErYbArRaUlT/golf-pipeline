"""Calibrate the engine's aero coefficients, report the fit, and plot a shot.

Calibrates drag / spin-drag / lift against the TrackMan PGA Tour bag (12 clubs
spanning the spin range), reports the carry residual, then runs an *independent*
check against our own measured TrackMan driver radar in the warehouse - does the
bag-calibrated engine reproduce a carry it was never fit on? Finally it renders a
mid-iron trajectory at the calibrated coefficients.

Run via `just calibrate`. Needs the `modeling` group and BigQuery ADC.
"""

from __future__ import annotations

import os

from . import warehouse
from .benchmarks import calibrate_engine, load_trackman_pga
from .physics import simulate
from .viz import plot_trajectory


def main() -> None:
    result = calibrate_engine()
    print(f"calibrated on {result.n_shots} TrackMan tour clubs (driver -> wedge)\n")
    print("=== aerodynamic coefficients ===")
    print(f"  Cd        = {result.cd:.4f}")
    print(f"  Cl_coeff  = {result.cl:.4f}")
    print(f"  Cd_spin   = {result.cd_spin:.4f}  (drag rise with spin)")
    print(
        f"  carry MAE: {result.mae_before_yards:.1f} yds (defaults) "
        f"-> {result.mae_after_yards:.1f} yds (calibrated), median "
        f"{result.median_ae_after_yards:.1f}"
    )

    mae, n = warehouse.driver_radar_check(warehouse.client(), result.cd, result.cl, result.cd_spin)
    print(f"\nindependent check vs measured driver radar ({n} shots): {mae:.1f} yds carry MAE")

    # Plot a 7-iron from the tour bag at the calibrated coefficients.
    club = next(c for c in load_trackman_pga() if c.club == "7-iron")
    traj = simulate(club.to_shot_input(), result.cd, result.cl, result.cd_spin)
    os.makedirs("modeling/artifacts", exist_ok=True)
    out = plot_trajectory(
        traj,
        title=f"{club.club} - calibrated (TrackMan carry {club.carry_yards:.0f} yds)",
        out_path="modeling/artifacts/trajectory.png",
    )
    print(f"\ntrajectory plotted -> {out}")


if __name__ == "__main__":
    main()

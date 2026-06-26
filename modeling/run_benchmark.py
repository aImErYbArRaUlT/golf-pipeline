"""Show the calibrated engine's carry vs TrackMan's published carry, per club.

The engine is calibrated on these tour averages (they span the bag's full spin
range - see calibration.py), so this is the fit quality: how closely one
aerodynamic model reproduces every club driver-through-wedge. The independent,
out-of-sample check (our own measured driver radar) is reported by `just
calibrate`.

Run via `just benchmark`. Needs the `modeling` group (no warehouse).
"""

from __future__ import annotations

import os

import numpy as np

from .benchmarks import calibrate_engine, load_trackman_pga
from .physics import simulate
from .viz import plot_benchmark


def main() -> None:
    calib = calibrate_engine()
    print(
        f"calibrated on the TrackMan tour bag: Cd={calib.cd:.3f}, "
        f"Cl_coeff={calib.cl:.3f}, Cd_spin={calib.cd_spin:.3f}\n"
    )

    clubs = load_trackman_pga()
    header = f"{'club':<10}{'ball':>7}{'launch':>8}{'spin':>7}{'pub':>7}{'sim':>7}{'err':>7}"
    print(header)
    print("-" * len(header))

    published, simulated, errors = [], [], []
    for c in clubs:
        sim = simulate(c.to_shot_input(), calib.cd, calib.cl, calib.cd_spin).carry_yards
        err = sim - c.carry_yards
        published.append(c.carry_yards)
        simulated.append(sim)
        errors.append(abs(err))
        print(
            f"{c.club:<10}{c.ball_speed_mph:>7.0f}{c.launch_angle_deg:>8.1f}"
            f"{c.spin_rate_rpm:>7.0f}{c.carry_yards:>7.0f}{sim:>7.0f}{err:>+7.0f}"
        )

    print(
        f"\ncarry MAE across the bag: {np.mean(errors):.1f} yds - one aerodynamic model, "
        f"every club. (Spin-dependent drag is what makes this possible.)"
    )

    os.makedirs("modeling/artifacts", exist_ok=True)
    out = plot_benchmark(
        [c.club for c in clubs],
        np.array(published),
        np.array(simulated),
        title="Calibrated engine vs TrackMan PGA Tour carry, whole bag",
        out_path="modeling/artifacts/benchmark.png",
    )
    print(f"benchmark plotted -> {out}")


if __name__ == "__main__":
    main()

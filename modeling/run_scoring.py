"""Score the bag with strokes-gained, on real gold data (Stage C).

Three things, building on the dispersion bag:

1. Validate the benchmark `expected_strokes` curve against commonly-published
   tour numbers (the model has to encode sane values to be useful).
2. A worked strokes-gained example for one shot.
3. The real payoff: for each club, the expected strokes to hole out from its
   stock distance using the player's *validated* carry spread, next to a tight
   low-handicap benchmark spread. The gap is the strokes that distance
   inconsistency is costing - a genuine strokes-gained insight, computed only
   from quantities Stage B validated (carry spread), with the biased lateral
   and absolute-carry dimensions left out by design.

Run via `just scoring [skill]`. With a skill (tour/scratch/amateur) it runs on a
synthetic bag and needs no warehouse; without one it loads the richest real bag
(BigQuery ADC). Needs the `modeling` group.
"""

from __future__ import annotations

import os
import sys

import numpy as np

from .scoring import FAIRWAY, GREEN, ROUGH, expected_strokes, hole_out_strokes, strokes_gained
from .synthetic import resolve_bag
from .viz import plot_scoring

_BENCHMARK_SIGMA = 5.0  # illustrative low-handicap carry std (yards)


def _print_baseline() -> None:
    print("expected strokes to hole out (benchmark) - validates the scoring curve")
    print(f"{'distance':>10}{'fairway':>10}{'rough':>10}{'green/putt':>12}")
    for dist in (20, 40, 60, 100, 150, 200):
        putt = expected_strokes(dist, GREEN) if dist <= 30 else float("nan")
        print(
            f"{dist:>8}yd{expected_strokes(dist, FAIRWAY):>10.2f}"
            f"{expected_strokes(dist, ROUGH):>10.2f}{putt:>12.2f}"
        )
    sg = strokes_gained(150, FAIRWAY, 4.0, GREEN)  # 150 fairway to ~12 ft
    print(f"\nexample: a 150yd fairway shot to 12 ft -> strokes gained {sg:+.2f}\n")


def main() -> None:
    skill = sys.argv[1] if len(sys.argv) > 1 else ""
    bag = resolve_bag(skill or None)
    print(f"player: {bag.player} ({bag.source}) - {len(bag.clubs)} clubs\n")
    _print_baseline()

    rng = np.random.default_rng(0)
    rows: list[tuple[str, float, float]] = []
    print(f"{'club':<15}{'stock yd':>9}{'your E[str]':>12}{'tight E[str]':>13}{'gap':>7}")
    print("-" * 56)
    for cs in bag.clubs:
        pin = cs.measured_carry_mean
        # Your distribution: the engine's validated carry spread, recentred onto
        # the monitor's measured mean (so we use the trusted location, not the
        # driver-biased absolute carry). Lateral is left out - see module docstring.
        engine_carry = cs.dispersion.landings_carry
        your_carry = engine_carry - engine_carry.mean() + pin
        your = hole_out_strokes(pin, your_carry)
        # Benchmark: same stock distance, a tight low-handicap carry spread.
        bench_carry = rng.normal(pin, _BENCHMARK_SIGMA, size=your_carry.size)
        bench = hole_out_strokes(pin, bench_carry)

        rows.append((cs.dispersion.club, your.expected_strokes, bench.expected_strokes))
        print(
            f"{cs.dispersion.club:<15}{pin:>9.0f}{your.expected_strokes:>12.2f}"
            f"{bench.expected_strokes:>13.2f}{your.expected_strokes - bench.expected_strokes:>7.2f}"
        )

    avg_gap = float(np.mean([y - b for _c, y, b in rows]))
    print(f"\naverage gap: {avg_gap:+.2f} strokes/shot left to distance control.")

    os.makedirs("modeling/artifacts", exist_ok=True)
    title = (
        f"Strokes to hole out from stock distance - {bag.player}\n"
        f"your carry spread vs a tight benchmark"
    )
    out = plot_scoring(rows, title=title, out_path="modeling/artifacts/scoring.png")
    print(f"scoring plotted -> {out}")


if __name__ == "__main__":
    main()

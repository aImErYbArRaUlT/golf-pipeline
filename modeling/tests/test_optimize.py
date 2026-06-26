"""Optimiser tests (2-D) - the recommendation follows the geometry.

No warehouse: clubs are synthetic (carry, lateral) samples, holes are hand-built.
The checks are strategy logic - centre on the pin when it's safe, avoid water
whether it guards short or to one side, and never do worse than firing at the flag.
"""

from __future__ import annotations

import numpy as np
import pytest

from modeling.course import WATER, Hazard, Hole, Region
from modeling.optimize import evaluate_shot, optimize_shot


def _club(carry_mean, sigma_c, sigma_l, n=4000, seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(carry_mean, sigma_c, n), rng.normal(0.0, sigma_l, n)


def test_no_hazard_aims_at_the_pin():
    carry, lat = _club(150, 5, 5)
    best = optimize_shot([("7i", carry, lat)], Hole(pin_distance_yards=150))[0]
    assert best.aim_distance_yards == pytest.approx(150, abs=3.5)
    assert best.aim_lateral_yards == pytest.approx(0, abs=3.5)


def test_water_in_front_raises_expected_strokes():
    carry, lat = _club(150, 14, 8)
    front_water = Hazard(Region(near=120, far=144, left=-40, right=40), kind=WATER)
    dry = evaluate_shot(carry, lat, 150, 0, Hole(pin_distance_yards=150))
    wet = evaluate_shot(carry, lat, 150, 0, Hole(pin_distance_yards=150, hazards=(front_water,)))
    assert wet.expected_strokes > dry.expected_strokes
    assert wet.penalty_pct > 0.0


def test_optimiser_steers_away_from_a_right_side_pond():
    carry, lat = _club(150, 6, 11)
    pond = Hazard(Region(near=135, far=165, left=6, right=45), kind=WATER)
    hole = Hole(pin_distance_yards=150, hazards=(pond,))
    best = optimize_shot([("7i", carry, lat)], hole)[0]
    naive = evaluate_shot(carry, lat, 150, 0, hole)
    assert best.aim_lateral_yards < 0  # aim left, away from the water
    assert best.expected_strokes <= naive.expected_strokes + 1e-9
    assert best.penalty_pct <= naive.penalty_pct + 1e-9


def test_results_are_ranked():
    a = _club(150, 6, 6)
    b = _club(170, 9, 9, seed=1)
    out = optimize_shot([("7i", *a), ("5i", *b)], Hole(pin_distance_yards=150))
    assert [c.expected_strokes for c in out] == sorted(c.expected_strokes for c in out)

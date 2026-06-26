"""Scoring tests - the benchmark curve must encode sane values and the right shape.

No warehouse: the baseline is a fixed model, and hole-out is checked on synthetic
landing clouds. Assertions are mostly about shape (monotone, lie ordering, tighter
dispersion scores better) plus a couple of well-known published anchors.
"""

from __future__ import annotations

import numpy as np
import pytest

from modeling.scoring import (
    FAIRWAY,
    GREEN,
    RECOVERY,
    ROUGH,
    SAND,
    TEE,
    expected_strokes,
    expected_strokes_array,
    hole_out_strokes,
    strokes_gained,
)


def test_short_game_taxes_around_the_green_by_difficulty():
    # A weaker short game adds strokes scaled by difficulty: a tap-in barely moves, a
    # long putt and a bunker shot are taxed, and it is never cheaper than the benchmark.
    d = np.array([0.67, 6.7, 5.0])  # 2 ft putt, 20 ft putt, 5 yd bunker
    lie = np.array([GREEN, GREEN, SAND])
    tour = expected_strokes_array(d, lie, short_game=0.0)
    loose = expected_strokes_array(d, lie, short_game=0.40)
    assert (loose >= tour).all()
    assert loose[0] - tour[0] < 0.02  # tap-in: negligible
    assert loose[1] - tour[1] > 0.10  # long putt: taxed
    assert loose[2] - tour[2] > 0.30  # bunker: taxed more
    # The off-green gap is heavier per excess stroke than putting, so a green miss
    # costs more than a putt - this is what leans a weak player's aim onto the green.
    rate_putt = (loose[1] - tour[1]) / (tour[1] - 1.0)
    rate_sand = (loose[2] - tour[2]) / (tour[2] - 1.0)
    assert rate_sand > rate_putt


def test_holed_is_zero():
    assert expected_strokes(0.0, FAIRWAY) == 0.0
    assert expected_strokes(0.0, GREEN) == 0.0


def test_known_benchmark_anchors():
    # Verified values from Broadie's published PGA-Tour benchmark.
    assert expected_strokes(100, FAIRWAY) == pytest.approx(2.80, abs=0.02)
    assert expected_strokes(120, FAIRWAY) == pytest.approx(2.85, abs=0.02)
    assert expected_strokes(120, ROUGH) == pytest.approx(3.08, abs=0.02)
    assert expected_strokes(120, ROUGH) - expected_strokes(120, FAIRWAY) == pytest.approx(
        0.23, abs=0.03
    )
    assert expected_strokes(1.0, GREEN) == pytest.approx(1.04, abs=0.02)  # 3-ft putt
    assert expected_strokes(450, TEE) == pytest.approx(2.38 + 0.0041 * 450, abs=1e-9)


def test_expected_strokes_increases_with_distance():
    fairway = [expected_strokes(d, FAIRWAY) for d in (40, 80, 120, 160, 200)]
    assert fairway == sorted(fairway)
    putts = [expected_strokes(d, GREEN) for d in (1, 2, 5, 10)]
    assert putts == sorted(putts)


def test_lie_ordering_worse_costs_more():
    d = 130
    assert (
        expected_strokes(d, FAIRWAY)
        < expected_strokes(d, ROUGH)
        < expected_strokes(d, SAND)
        < expected_strokes(d, RECOVERY)
    )


def test_unknown_lie_raises():
    with pytest.raises(ValueError, match="lie"):
        expected_strokes(100, "water")


def test_strokes_gained_sign():
    assert strokes_gained(150, FAIRWAY, 4.0, GREEN) > 0  # good approach to 12 ft
    assert strokes_gained(150, FAIRWAY, 150, ROUGH) < 0  # chunked, went nowhere


def test_perfect_shot_is_about_two_strokes():
    pin = 100.0
    perfect = np.full(1000, pin)  # every ball finishes at the pin
    score = hole_out_strokes(pin, perfect)
    assert score.frac_on_green == 1.0
    assert score.expected_strokes == pytest.approx(2.0, abs=0.1)  # shot + tap-in


def test_tighter_dispersion_scores_better():
    pin, rng = 100.0, np.random.default_rng(0)
    tight = hole_out_strokes(pin, rng.normal(pin, 3.0, 2000))
    wide = hole_out_strokes(pin, rng.normal(pin, 25.0, 2000))
    assert tight.expected_strokes < wide.expected_strokes
    assert tight.frac_on_green > wide.frac_on_green


def test_green_difficulty_taxes_putts_and_more_for_weak_players() -> None:
    # A hard green costs more strokes around and on it, and the interaction makes that
    # cost bigger for a weaker player than a tour pro - the green is shared, skill is
    # per-player, the tax is their product.
    d = np.array([8.0])  # ~24 ft
    lie = np.array([GREEN])
    flat = expected_strokes_array(d, lie, short_game=0.25)[0]
    hard = expected_strokes_array(d, lie, short_game=0.25, green_difficulty=1.0)[0]
    assert hard > flat  # a severe green costs more

    def gap(sg: float) -> float:
        base = expected_strokes_array(d, lie, short_game=sg)[0]
        tough = expected_strokes_array(d, lie, short_game=sg, green_difficulty=1.0)[0]
        return float(tough - base)

    assert gap(0.4) > gap(0.0) > 0  # the same green taxes a weak putter more than a pro

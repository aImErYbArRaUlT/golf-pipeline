"""Whole-hole planner tests - value iteration agrees with the single-shot scorer.

The bag is synthetic (no warehouse). The load-bearing check is that the planner's
value on a one-shot hole matches the validated `optimize_shot`; the rest assert
the plan is sensible and that water can only raise the score.
"""

from __future__ import annotations

import math

import pytest

from modeling.course import WATER, Hazard, Hole, Region
from modeling.optimize import optimize_shot
from modeling.planner import plan_hole
from modeling.synthetic import TOUR, synthetic_bag

_BAG = synthetic_bag("pga", TOUR)  # calibrates once at import


def _clubs(bag):
    return [
        (
            cs.dispersion.club,
            cs.dispersion.landings_carry
            - cs.dispersion.landings_carry.mean()
            + cs.measured_carry_mean,
            cs.dispersion.landings_lateral,
        )
        for cs in bag.clubs
    ]


def test_one_shot_hole_matches_single_shot_optimizer():
    hole = Hole(pin_distance_yards=130, green_radius_yards=8)
    plan = plan_hole(hole, _BAG)
    opt = optimize_shot(_clubs(_BAG), hole)[0]
    assert plan.tee_value == pytest.approx(opt.expected_strokes, abs=0.25)


def test_par4_is_sensible_and_rolls_out():
    plan = plan_hole(Hole(pin_distance_yards=420, green_radius_yards=8), _BAG)
    assert math.isfinite(plan.tee_value)
    assert 3.0 < plan.tee_value < 5.0  # a tour player on a par 4
    assert plan.shots  # a sensible sequence (a short wedge approach can fold into the floor)
    assert plan.shots[0].aim_x > 230  # the first shot is a long one (a wood)


def test_water_can_only_raise_the_score():
    pin = 420
    dry = Hole(pin_distance_yards=pin, green_radius_yards=8)
    wet = Hole(
        pin_distance_yards=pin,
        green_radius_yards=8,
        hazards=(Hazard(Region(pin - 25, pin - 6, 4, 50), kind=WATER),),
    )
    assert plan_hole(wet, _BAG).tee_value >= plan_hole(dry, _BAG).tee_value - 1e-6


def test_weaker_short_game_costs_strokes():
    # A worse short game raises the floor (getting up and down is dearer), so the
    # expected score from the tee can only go up.
    hole = Hole(pin_distance_yards=420, green_radius_yards=8)
    tour = plan_hole(hole, _BAG, short_game=0.0)
    loose = plan_hole(hole, _BAG, short_game=0.40)
    assert loose.tee_value > tour.tee_value

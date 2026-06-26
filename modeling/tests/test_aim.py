"""Approach aim from the dispersion: where to aim relative to the flag."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from shapely.geometry import Point

from modeling.aim import aim_for_pin, clamp_pin_to_green
from modeling.course import load_course
from modeling.players import profile_bag


def test_green_slopes_loaded_and_consistent() -> None:
    holes = load_course("torrey_pines_south")
    assert sum(1 for h in holes if h.green_slope != (0.0, 0.0)) >= 15  # USGS tilt on most
    h = next(h for h in holes if h.ref == 8)
    c = h.green.centroid
    a, b = h.green_slope  # the gradient points uphill
    up = float(h.elevation_on_green(np.array([c.x + a]), np.array([c.y + b]))[0])
    down = float(h.elevation_on_green(np.array([c.x - a]), np.array([c.y - b]))[0])
    assert up > down


def test_slope_pulls_aim_below_a_back_pin() -> None:
    # Hole 8's green falls toward the front; a back pin sits above the hole, so the aim
    # should be pulled short to leave an uphill putt. Use a clearly steep version of the
    # same fall line so the pull exceeds the aim grid, not a gentle real-world tilt.
    h = next(h for h in load_course("torrey_pines_south") if h.ref == 8)
    gx0, gy0, gx1, gy1 = h.green.bounds
    pin = clamp_pin_to_green(h.green, (gx0 + 0.85 * (gx1 - gx0), gy0 + 0.5 * (gy1 - gy0)))
    bag = profile_bag("PGA tour pro")
    a, b = h.green_slope
    mag = (a * a + b * b) ** 0.5 or 1.0
    steep = replace(h, green_slope=(a / mag * 0.08, b / mag * 0.08))  # 8% in the fall direction
    sloped = aim_for_pin(steep, bag, pin, 175)
    flat = aim_for_pin(replace(h, green_slope=(0.0, 0.0)), bag, pin, 175)
    assert sloped.long_yds < flat.long_yds  # slope pulls the aim shorter / below the hole


def test_weaker_short_game_aims_onto_more_green() -> None:
    # A back pin on hole 8 sits near the back bunker. A weaker short game can't recover
    # from a miss, so it bails onto more of the green and scores the worse short game.
    h = next(h for h in load_course("torrey_pines_south") if h.ref == 8)
    gx0, gy0, gx1, gy1 = h.green.bounds
    pin = clamp_pin_to_green(h.green, (gx0 + 0.9 * (gx1 - gx0), gy0 + 0.5 * (gy1 - gy0)))
    bag = profile_bag("Mid handicap")
    tour = aim_for_pin(h, bag, pin, 170, short_game=0.0)
    loose = aim_for_pin(h, bag, pin, 170, short_game=0.40)
    assert loose.on_green_pct >= tour.on_green_pct  # bails onto the green
    assert loose.expected > tour.expected  # and prices the weaker short game


def test_pin_is_clamped_onto_the_green() -> None:
    # The green is irregular, so a bounding-box corner sits off the putting surface;
    # a flag must never be off the green, so it's snapped inside.
    h = next(h for h in load_course("torrey_pines_south") if h.ref == 18)
    gx0, gy0, _, _ = h.green.bounds
    corner = (gx0, gy0)
    assert not h.green.contains(Point(corner))  # the raw bbox corner is off the green
    pin = clamp_pin_to_green(h.green, corner)
    assert h.green.contains(Point(pin))  # snapped onto the surface


def test_aim_is_well_formed() -> None:
    h = next(h for h in load_course("torrey_pines_south") if h.ref == 8)  # a par 3
    gc = h.green.centroid
    advice = aim_for_pin(h, profile_bag("PGA tour pro"), (gc.x, gc.y), 175)
    assert advice.club  # picked a club
    assert 0.0 <= advice.on_green_pct <= 100.0
    assert -30 < advice.long_yds < 15 and -25 < advice.right_yds < 25


def test_wider_player_aims_safer_from_a_tucked_pin() -> None:
    # A pin tucked left, by the 18th pond. The tighter player can fire near it; the
    # wider player is walked away from the water (further right / more conservative).
    h = next(h for h in load_course("torrey_pines_south") if h.ref == 18)
    gc = h.green.centroid
    pin = (gc.x, gc.y - 8)  # left, toward the pond
    pro = aim_for_pin(h, profile_bag("PGA tour pro"), pin, 150)
    senior = aim_for_pin(h, profile_bag("Senior"), pin, 150)
    assert senior.right_yds >= pro.right_yds  # senior aimed further from the water
    offset = abs(senior.right_yds) + abs(senior.long_yds)
    assert offset >= abs(pro.right_yds) + abs(pro.long_yds)  # and more conservatively overall
    assert pro.on_green_pct >= senior.on_green_pct  # the tight player holds it more often

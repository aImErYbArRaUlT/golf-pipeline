"""The OSM-derived real course: loading, polygon lie classification, planning."""

from __future__ import annotations

import numpy as np

from modeling.course import CourseHole, TeeBox, load_course
from modeling.planner import plan_hole
from modeling.scoring import GREEN, RECOVERY, ROUGH
from modeling.synthetic import AMATEUR, TOUR, synthetic_bag


def test_pin_difficulty_rises_when_short_sided() -> None:
    # A green with water hard against its left side: a flag tucked left short-sides a miss
    # into the hazard, so the surface must rate it harder than an open flag on the right.
    from shapely.geometry import Point
    from shapely.geometry import Polygon as P

    from modeling.aim import pin_difficulty_surface

    green = P([(380, -12), (410, -12), (410, 12), (380, 12)])
    water = P([(384, -30), (406, -30), (406, -12), (384, -12)])  # short-left of the green
    hole = CourseHole(
        course="T",
        ref=1,
        par=3,
        pin_distance_yards=395.0,
        bearing_deg=0.0,
        green=green,
        fairway=Point(0, 0).buffer(0),
        bunkers=Point(0, 0).buffer(0),
        water=water,
        _bbox=(-10.0, 430.0, -40.0, 40.0),
    )
    surf = pin_difficulty_surface(
        hole, synthetic_bag("pga", AMATEUR), from_distance=160.0, short_game=0.3, step=4.0
    )
    assert surf and surf[0].over_easiest == 0.0  # sorted easiest first
    left = min(surf, key=lambda p: p.y)  # tucked toward the water
    right = max(surf, key=lambda p: p.y)  # open side
    assert left.expected > right.expected  # short-siding makes the left flag harder


def _dogleg_hole() -> CourseHole:
    """A long dogleg-right hole: the playable corridor runs tee -> a corner at (250, +120)
    -> the green at (480, 0), so the straight tee->pin line cuts across trees (a recovery
    lie) and the green can't be reached straight. The planner must route around it."""
    from shapely.geometry import LineString, Point

    route = LineString([(0, 0), (250, 120), (480, 0)])
    fairway = route.buffer(26)
    green = Point(480, 0).buffer(9)
    playable = fairway.union(green).buffer(20)
    return CourseHole(
        course="Test",
        ref=1,
        par=5,
        pin_distance_yards=480.0,
        bearing_deg=0.0,
        green=green,
        fairway=fairway,
        bunkers=Point(0, 0).buffer(0),  # empty
        water=Point(0, 0).buffer(0),
        _bbox=(-10.0, 510.0, -70.0, 160.0),
        playable=playable,
        tees=(TeeBox(0.0, 0.0, 480.0),),
    )


def test_outside_the_playable_corridor_is_recovery() -> None:
    h = _dogleg_hole()
    # A point on the straight tee->pin line, inside the dogleg, is trees (recovery).
    assert h.lie_at(np.array([150.0]), np.array([0.0]))[0] == RECOVERY
    # A point in the corridor at the corner is playable (fairway), not recovery.
    assert h.lie_at(np.array([175.0]), np.array([84.0]))[0] != RECOVERY


def test_planner_routes_around_a_dogleg() -> None:
    # Given a recovery corridor, the tee shot is aimed around the corner (off the
    # straight line), not fired through the trees - the engine plays it like a person.
    h = _dogleg_hole()
    plan = plan_hole(h, synthetic_bag("pga", TOUR), cell_size=6.0, tee_xy=(0.0, 0.0))
    assert plan.shots[0].aim_y > 30.0  # routed toward the +y corner, not aim_y ~ 0


def test_loads_full_eighteen() -> None:
    holes = load_course("torrey_pines_south")
    assert len(holes) == 18
    assert [h.ref for h in holes] == list(range(1, 19))
    assert sum(h.par for h in holes) == 72  # Torrey South is a par 72
    assert all(not h.green.is_empty for h in holes)


def test_pin_on_downrange_axis() -> None:
    # Each hole is framed tee->pin, so the green sits ~on the centreline (lateral 0)
    # and pin distances are realistic championship yardages.
    holes = load_course("torrey_pines_south")
    for h in holes:
        cx, cy = h.green.centroid.x, h.green.centroid.y
        assert abs(cx - h.pin_distance_yards) < 25.0
        assert abs(cy) < 20.0
    assert 150 < min(h.pin_distance_yards for h in holes) < 260  # the par 3s
    assert 560 < max(h.pin_distance_yards for h in holes) < 640  # the long par 5s


def test_lie_classification_by_polygon() -> None:
    h = load_course("torrey_pines_south")[8]  # hole 9
    inside = h.green.representative_point()
    assert h.lie_at(np.array([inside.x]), np.array([inside.y]))[0] == GREEN
    # A point far off the corridor is rough, not green/fairway.
    far = h.bounds()[3] - 1.0  # near the lateral edge of the grid
    assert h.lie_at(np.array([h.pin_distance_yards / 2]), np.array([far]))[0] == ROUGH


def test_water_hole_has_penalty_area() -> None:
    h = next(h for h in load_course("torrey_pines_south") if h.ref == 18)
    assert not h.water.is_empty  # the pond by the 18th green
    wp = h.water.representative_point()
    assert h.in_penalty(np.array([wp.x]), np.array([wp.y]))[0]
    assert h.penalty_drop_x() is not None


def test_plan_real_hole_is_sane() -> None:
    holes = load_course("torrey_pines_south")
    bag = synthetic_bag("pga", TOUR)
    h = next(h for h in holes if h.ref == 1)  # par 4
    plan = plan_hole(h, bag, cell_size=6.0)
    assert isinstance(h, CourseHole)
    assert len(plan.shots) >= 1
    assert plan.shots[0].club == "Driver"  # 445-yd par 4 starts with a drive
    assert 3.0 < plan.tee_value < 5.5  # a tour player on a par 4


def test_elevation_loads_and_interpolates() -> None:
    from modeling.course import Hole

    holes = load_course("torrey_pines_south")
    assert any(h.elevation for h in holes)  # USGS terrain is present
    h3 = next(h for h in holes if h.ref == 3)  # the cliffside downhill 3rd
    green_elev = float(h3.elevation_at(np.array([h3.pin_distance_yards]))[0])
    assert green_elev < -8.0  # green sits well below the tee (~13 yds)
    assert float(Hole(400).elevation_at(np.array([200.0]))[0]) == 0.0  # flat hole = 0


def test_downhill_plays_easier_than_flat() -> None:
    from dataclasses import replace

    h = next(h for h in load_course("torrey_pines_south") if h.ref == 3)  # downhill par 3
    bag = synthetic_bag("pga", TOUR)
    downhill = plan_hole(h, bag, cell_size=6.0)
    flat = plan_hole(replace(h, elevation=()), bag, cell_size=6.0)
    assert downhill.tee_value < flat.tee_value  # the green plays closer downhill


def test_tee_boxes_load_and_shorten() -> None:
    h = next(h for h in load_course("torrey_pines_south") if h.ref == 18)
    assert len(h.tees) >= 2
    back, fwd = h.tee_for("Back"), h.tee_for("Forward")
    assert back.yards > fwd.yards  # a forward tee plays shorter
    assert fwd.downrange > back.downrange  # and sits further up the hole
    assert abs(back.yards - h.pin_distance_yards) < 15  # back ~ the championship yardage


def test_forward_tee_is_not_harder() -> None:
    h = next(h for h in load_course("torrey_pines_south") if h.ref == 18)
    bag = synthetic_bag("pga", TOUR)
    back, fwd = h.tee_for("Back"), h.tee_for("Forward")
    p_back = plan_hole(h, bag, cell_size=6.0, tee_xy=(back.downrange, back.lateral))
    p_fwd = plan_hole(h, bag, cell_size=6.0, tee_xy=(fwd.downrange, fwd.lateral))
    assert p_fwd.tee_value <= p_back.tee_value + 0.05  # shorter hole, no harder
    assert len(p_fwd.shots) >= 1


def test_one_stock_shape_on_every_shot() -> None:
    # A player has ONE shape; the planner aims it, it doesn't flip draw/fade per shot.
    from modeling.planner import SHAPE_SKEW

    h = next(h for h in load_course("torrey_pines_south") if h.ref == 18)
    bag = synthetic_bag("pga", TOUR)
    plan = plan_hole(h, bag, cell_size=6.0, skew=SHAPE_SKEW["draw"], shape="draw")
    assert len(plan.shots) >= 2
    assert {s.shape for s in plan.shots} == {"draw"}  # the same shape, every shot


def test_plan_plays_18_like_golf() -> None:
    # The 18th: a dogleg-left fairway (centred ~-15 in the driving zone) with a
    # pond by the green. The planner should play it like a golfer, not a robot.
    h = next(h for h in load_course("torrey_pines_south") if h.ref == 18)
    plan = plan_hole(h, synthetic_bag("pga", TOUR), cell_size=5.0)
    # Aims into the fairway (left), not down the straight tee->pin line (the rough).
    assert plan.shots[0].aim_y < -3.0
    # The driver is tee-only - it doesn't bomb it off the deck at a guarded green.
    assert all(s.club != "Driver" for s in plan.shots[1:])
    # Every shot is worked with a valid shape.
    assert all(s.shape in {"draw", "straight", "fade"} for s in plan.shots)

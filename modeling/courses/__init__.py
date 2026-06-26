"""Real golf courses for the engine, built from OpenStreetMap (see build.py).

Each course is a committed JSON of holes already projected into the engine's
(downrange, lateral) yard frame, so loading needs no network and no OSM parsing.
`course.load_course` turns one into the polygon `CourseHole`s the planner plays.
"""

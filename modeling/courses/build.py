"""Disposable preprocessor: OpenStreetMap golf course -> engine course JSON.

OSM maps a golf course as lat/lon polygons tagged `golf=green|fairway|bunker`,
`golf=hole` centrelines (carrying `par`), and `golf=water_hazard`. The engine
plays a hole in a planar (downrange, lateral) yard frame with the pin on the
downrange axis. This script bridges the two, once, into a committed JSON the
runtime loads - so the engine never depends on OSM or a network at run time.

Per hole it: picks the green nearest a centreline end (that end is the pin, the
far end is the tee), builds the tee->pin frame, assigns the nearest fairway and the
bunkers/water/tees closest to this hole, projects every polygon into yards, and
(with --elevation) samples a downrange terrain profile from USGS.

Not part of the pipeline. Re-run only to regenerate the data:

    uv run --group modeling python -m modeling.courses.build --osm /path/to/overpass.json \
        --name torrey_pines_south --title "Torrey Pines South Course" --elevation

The Overpass query and the USGS elevation source are documented in SOURCES.md.
"""

from __future__ import annotations

import argparse
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path

_M_PER_DEG = 111_320.0  # metres per degree latitude (and longitude at the equator)
_YD_PER_M = 1.0 / 0.9144
_HERE = Path(__file__).parent

# USGS National Map elevation point service - a read-only .gov endpoint that
# returns one elevation number (metres) per lat/lon. No downloads; we sample a few
# points per hole and commit the numbers, so the runtime never hits the network.
_EPQS = "https://epqs.nationalmap.gov/v1/json"


def _fetch_elevation_m(lat: float, lon: float) -> float | None:
    """Ground elevation (metres) at a lat/lon from USGS EPQS, or None on failure."""
    url = (
        _EPQS
        + "?"
        + urllib.parse.urlencode(
            {"x": lon, "y": lat, "wkid": 4326, "units": "Meters", "includeDate": "false"}
        )
    )
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "golf-pipeline/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (https .gov)
                value = json.loads(r.read()).get("value")
            return float(value) if value not in (None, "") else None
        except Exception:
            continue
    return None


def _green_slope(green_ll: list[tuple[float, float]], project) -> list[float]:
    """Fit a tilt plane to a green from USGS samples: returns the elevation gradient
    [d/downrange, d/lateral] in yards-rise per yard. The fall line is its negative -
    what tells the aim which way is below the hole. [0, 0] if it can't be sampled."""
    import numpy as np
    from shapely.geometry import Point, Polygon

    poly = Polygon([(lon, lat) for lat, lon in green_ll]).buffer(0)
    if poly.is_empty:
        return [0.0, 0.0]
    minx, miny, maxx, maxy = poly.bounds
    samples = []
    for i in range(4):
        for j in range(4):
            lon = minx + (i + 0.5) / 4 * (maxx - minx)
            lat = miny + (j + 0.5) / 4 * (maxy - miny)
            if not poly.contains(Point(lon, lat)):
                continue
            e = _fetch_elevation_m(lat, lon)
            if e is None:
                continue
            dr, lt = project((lat, lon))
            samples.append((dr, lt, e * _YD_PER_M))
    if len(samples) < 4:
        return [0.0, 0.0]
    coef = np.linalg.lstsq(
        np.array([[s[0], s[1], 1.0] for s in samples]),
        np.array([s[2] for s in samples]),
        rcond=None,
    )[0]
    return [round(float(coef[0]), 4), round(float(coef[1]), 4)]


def _sample_polyline(pts: list[tuple[float, float]], n: int) -> list[tuple[float, float]]:
    """`n` points evenly spaced along a (lat, lon) polyline by cumulative length."""
    if len(pts) < 2:
        return pts
    seg = [_metres(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    total = sum(seg) or 1.0
    cum = [0.0]
    for s in seg:
        cum.append(cum[-1] + s)
    out = []
    for k in range(n):
        d = total * k / (n - 1)
        i = max(0, min(len(seg) - 1, next((j for j in range(len(seg)) if cum[j + 1] >= d), 0)))
        f = (d - cum[i]) / (seg[i] or 1.0)
        out.append(
            (
                pts[i][0] + f * (pts[i + 1][0] - pts[i][0]),
                pts[i][1] + f * (pts[i + 1][1] - pts[i][1]),
            )
        )
    return out


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text())["elements"]


def _ring(el: dict) -> list[tuple[float, float]]:
    """A way's node coordinates as (lat, lon) pairs."""
    return [(p["lat"], p["lon"]) for p in el.get("geometry", [])]


def _outer_rings(el: dict) -> list[list[tuple[float, float]]]:
    """Geometry rings for a way (its own nodes) or a multipolygon relation (outers)."""
    if el["type"] == "way":
        pts = _ring(el)
        return [pts] if len(pts) >= 3 else []
    rings = [
        [(p["lat"], p["lon"]) for p in m.get("geometry", [])]
        for m in el.get("members", [])
        if m.get("role") == "outer"
    ]
    return [r for r in rings if len(r) >= 3]


def _largest_ring(el: dict) -> list[tuple[float, float]]:
    """The biggest outer ring (by bbox area) - the feature's main extent."""
    rings = _outer_rings(el)
    if not rings:
        return []

    def bbox_area(r: list[tuple[float, float]]) -> float:
        lats = [p[0] for p in r]
        lons = [p[1] for p in r]
        return (max(lats) - min(lats)) * (max(lons) - min(lons))

    return max(rings, key=bbox_area)


def _centroid(ring: list[tuple[float, float]]) -> tuple[float, float]:
    return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Equirectangular distance in metres between two (lat, lon) points."""
    mlat = math.radians(a[0] + b[0]) / 2
    dn = (a[0] - b[0]) * _M_PER_DEG
    de = (a[1] - b[1]) * _M_PER_DEG * math.cos(mlat)
    return math.hypot(dn, de)


def _projector(tee: tuple[float, float], pin: tuple[float, float]):
    """A function (lat, lon) -> [downrange_yd, lateral_yd] in the tee->pin frame.

    Downrange points from tee to pin; lateral is + to the player's right. The pin
    lands on the downrange axis (lateral 0) by construction, so the engine's
    `remaining = hypot(pin_distance - x, y)` holds unchanged.
    """
    mlon = _M_PER_DEG * math.cos(math.radians(tee[0]))
    pe = (pin[1] - tee[1]) * mlon
    pn = (pin[0] - tee[0]) * _M_PER_DEG
    length = math.hypot(pe, pn)
    de, dn = pe / length, pn / length  # downrange unit (east, north)
    re, rn = dn, -de  # right unit (90deg clockwise)

    def project(pt: tuple[float, float]) -> list[float]:
        e = (pt[1] - tee[1]) * mlon
        n = (pt[0] - tee[0]) * _M_PER_DEG
        return [round((e * de + n * dn) * _YD_PER_M, 1), round((e * re + n * rn) * _YD_PER_M, 1)]

    bearing = math.degrees(math.atan2(de, dn)) % 360.0  # compass bearing tee->pin (0 = N)
    return project, length * _YD_PER_M, bearing


def _nearest_hole(centroid: tuple[float, float], holes: list[dict]) -> int:
    """Index of the hole whose centreline passes closest to a feature centroid."""
    return min(
        range(len(holes)),
        key=lambda h: min(_metres(centroid, v) for v in holes[h]["line"]),
    )


def build(osm_path: Path, name: str, title: str, elevation: bool = False) -> dict:
    elements = _load(osm_path)
    by_golf: dict[str, list[dict]] = {}
    for el in elements:
        tag = el.get("tags", {}).get("golf")
        if tag:
            by_golf.setdefault(tag, []).append(el)

    holes = [
        {
            "ref": int(el["tags"]["ref"]),
            "par": int(el["tags"]["par"]),
            "line": _ring(el),
        }
        for el in by_golf.get("hole", [])
        if el["tags"].get("par") and len(_ring(el)) >= 2
    ]
    holes.sort(key=lambda h: h["ref"])

    greens = [
        (_centroid(_largest_ring(g)), g) for g in by_golf.get("green", []) if _largest_ring(g)
    ]
    fairways = [
        (_centroid(_largest_ring(f)), f) for f in by_golf.get("fairway", []) if _largest_ring(f)
    ]
    bunkers = [b for b in by_golf.get("bunker", []) if _largest_ring(b)]
    water = [
        w for w in (by_golf.get("water_hazard", []) + by_golf.get("water", [])) if _largest_ring(w)
    ]

    tees = [t for t in by_golf.get("tee", []) if _largest_ring(t)]

    # Assign each bunker / water / tee polygon to the single nearest hole.
    bunker_of = [_nearest_hole(_centroid(_largest_ring(b)), holes) for b in bunkers]
    water_of = [_nearest_hole(_centroid(_largest_ring(w)), holes) for w in water]
    tee_of = [_nearest_hole(_centroid(_largest_ring(t)), holes) for t in tees]

    out_holes = []
    used_greens: set[int] = set()
    for hi, hole in enumerate(holes):
        ends = [hole["line"][0], hole["line"][-1]]
        # Green nearest either centreline end; that end is the pin, the far end the tee.
        gi, end_i, _ = min(
            (
                (gi, ei, _metres(gc, e))
                for gi, (gc, _) in enumerate(greens)
                if gi not in used_greens
                for ei, e in enumerate(ends)
            ),
            key=lambda t: t[2],
        )
        used_greens.add(gi)
        pin = greens[gi][0]
        tee = ends[1 - end_i]
        project, pin_distance, bearing = _projector(tee, pin)

        def proj_ring(el: dict, project=project) -> list[list[float]]:
            return [project(p) for p in _largest_ring(el)]

        # Fairway: the one whose centroid passes closest to this centreline.
        fairway = min(
            fairways,
            key=lambda f: min(_metres(f[0], v) for v in hole["line"]),
            default=None,
        )
        bunkers_xy = [proj_ring(b) for b, of in zip(bunkers, bunker_of, strict=True) if of == hi]
        water_xy = [proj_ring(w) for w, of in zip(water, water_of, strict=True) if of == hi]

        # Tee boxes: project each assigned tee into the frame. A forward tee sits
        # further downrange (closer to the pin), so it plays shorter. Keep only
        # plausible ones (near the start, on line), longest first.
        tee_boxes = []
        for t, of in zip(tees, tee_of, strict=True):
            if of != hi:
                continue
            dr, lat = project(_centroid(_largest_ring(t)))
            yards = math.hypot(pin_distance - dr, lat)
            if -25.0 <= dr <= 0.45 * pin_distance and abs(lat) <= 45.0 and yards >= 70.0:
                tee_boxes.append(
                    {"downrange": round(dr, 1), "lateral": round(lat, 1), "yards": round(yards, 1)}
                )
        tee_boxes.sort(key=lambda t: -t["yards"])

        # Elevation profile (downrange -> ground height relative to the tee, yards)
        # sampled from USGS along the centreline. Uphill ground catches the ball
        # earlier (plays longer); downhill, later (plays shorter).
        elev_profile: list[list[float]] = []
        green_slope = [0.0, 0.0]
        if elevation:
            tee_m = _fetch_elevation_m(*tee)
            if tee_m is not None:
                seen: dict[int, float] = {}
                for pt in [tee, *_sample_polyline(hole["line"], 6), pin]:
                    em = _fetch_elevation_m(*pt)
                    if em is None:
                        continue
                    dr, _lat = project(pt)
                    seen[int(round(dr))] = round((em - tee_m) * _YD_PER_M, 1)
                elev_profile = [[float(d), seen[d]] for d in sorted(seen)]
            green_slope = _green_slope(_largest_ring(greens[gi][1]), project)

        out_holes.append(
            {
                "ref": hole["ref"],
                "par": hole["par"],
                "pin_distance_yards": round(pin_distance, 1),
                "bearing_deg": round(bearing, 1),
                "green_slope": green_slope,
                "elevation": elev_profile,
                "tees": tee_boxes,
                "green": proj_ring(greens[gi][1]),
                "fairway": proj_ring(fairway[1]) if fairway else [],
                "bunkers": bunkers_xy,
                "water": water_xy,
            }
        )

    return {
        "name": title,
        "slug": name,
        "source": "OpenStreetMap contributors (ODbL). See SOURCES.md.",
        "frame": "tee at origin; x downrange toward pin; y lateral (+ = right); yards.",
        "holes": out_holes,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--osm", required=True, type=Path, help="Overpass JSON (out geom)")
    ap.add_argument("--name", required=True, help="slug, e.g. torrey_pines_south")
    ap.add_argument("--title", required=True, help='display name, e.g. "Torrey Pines South Course"')
    ap.add_argument(
        "--elevation", action="store_true", help="sample USGS terrain per hole (needs network)"
    )
    args = ap.parse_args()

    course = build(args.osm, args.name, args.title, elevation=args.elevation)
    out = _HERE / f"{args.name}.json"
    out.write_text(json.dumps(course, separators=(",", ":")) + "\n")
    pars = sum(h["par"] for h in course["holes"])
    kb = out.stat().st_size // 1024
    print(f"{out.name}: {len(course['holes'])} holes, par {pars} ({kb} KB)")


if __name__ == "__main__":
    main()

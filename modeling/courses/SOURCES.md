# Course geometry - sources

Hole outlines (green, fairway, bunker, water polygons and hole centrelines with
par) come from **OpenStreetMap**, © OpenStreetMap contributors, licensed under
the **Open Database License (ODbL)**. https://www.openstreetmap.org/copyright

`build.py` projects the raw lat/lon geometry into the engine's planar
(downrange, lateral) yard frame and writes the committed `<slug>.json`. Re-run it
only to regenerate the data; the runtime never touches OSM or the network.

**Elevation** (with `--elevation`) is sampled from the **USGS National Map**
Elevation Point Query Service (`epqs.nationalmap.gov`), a public U.S. Geological
Survey endpoint that returns one ground-elevation number per lat/lon. Public-domain
U.S. government data; a handful of points per hole, committed as a downrange
height profile (relative to the tee), so the runtime stays offline. The same source
is sampled across each **green** (a grid clipped to the polygon) and fit to a tilt
plane - the `green_slope` gradient that tells the aim which way is below the hole.
USGS 3DEP resolves the gross green tilt (Torrey's greens read ~2-4%, falling
back-to-front; the 18th toward its pond), not subtle breaks.

## Torrey Pines South Course (`torrey_pines_south.json`)

OSM way `35679036` (`leisure=golf_course`, "Torrey Pines South Course"). Fetched
from the Overpass API with:

```overpassql
[out:json][timeout:120];
way(35679036);
map_to_area->.a;
(
  way["golf"](area.a);
  relation["golf"](area.a);
  way["natural"="water"](area.a);
);
out geom;
```

18 holes, par 72; pin distances total ~7,700 yds (the U.S. Open championship
tees). Per hole, `build.py` picks the green nearest a centreline end (that end is
the pin, the far end the tee), orients the tee→pin frame, assigns the nearest
fairway, the bunkers/water/tees closest to that hole, and projects every polygon to
yards. Each hole's **tee boxes** come from its OSM `golf=tee` polygons (~2-6 per
hole), kept longest-first with their downrange offset + yardage. Feature→hole
assignment is by proximity (OSM greens/bunkers/tees carry no hole ref), so a stray
feature near a shared boundary can land on the neighbouring hole.

To regenerate (the Overpass JSON is not committed - re-fetch with the query
above, `out geom`):

```sh
uv run --group modeling python -m modeling.courses.build \
    --osm overpass.json --name torrey_pines_south --title "Torrey Pines South Course"
```

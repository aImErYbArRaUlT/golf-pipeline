"""Player profiles - the same engine, different people (Phase: personalization).

The planner plans for a `ClubBag`; it doesn't care whose. A tour pro and a senior
are just different bags (different distances and dispersion), so they get different
optimal ways round the same hole - the bomber carries the hazard, the senior lays
up. These presets scale the tour bag down by swing speed and widen the dispersion
for lower skill, so the app can plan the course *for a person*, not an average.

This is the synthetic, illustrative path; a real player's bag comes from their own
ingested shots via `bag.load_bag` (warehouse) - same `ClubBag`, same planner.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass, replace
from statistics import median

from .bag import ClubBag, ClubStats
from .benchmarks import TourClub, calibrate_engine, load_trackman_lpga, load_trackman_pga
from .contracts import from_fct_row
from .dispersion import MIN_SHOTS, simulate_dispersion
from .synthetic import SCRATCH, _anchor_carry, skill_from_name, synthetic_bag

_TABLES = {"pga": load_trackman_pga, "lpga": load_trackman_lpga}

# Map a few common club-name variants onto the standard bag names.
_CLUB_ALIASES = {
    "dr": "Driver",
    "d": "Driver",
    "3w": "3-wood",
    "5w": "5-wood",
    "7w": "7-wood",
    "hy": "Hybrid",
    "hybrid": "Hybrid",
    "pw": "PW",
    "pitching wedge": "PW",
}


def _norm_club(name: str) -> str:
    """Best-effort normalisation of a club label onto the standard bag names."""
    s = name.strip().lower()
    if s in _CLUB_ALIASES:
        return _CLUB_ALIASES[s]
    s = s.replace(" ", "").replace("#", "")
    if s.endswith("i") and s[:-1].isdigit():  # 7i -> 7-iron
        s = s[:-1] + "iron"
    if s.endswith("iron") and s[:-4].isdigit():  # 7iron -> 7-iron
        return f"{s[:-4]}-iron"
    if s.endswith("wood") and s[:-4].isdigit():  # 3wood -> 3-wood
        return f"{s[:-4]}-wood"
    return name.strip()


# Raw launch-monitor export headers mapped onto the common-schema field names, keyed
# by the header with case and punctuation stripped ("Ball Speed [mph]" -> "ballspeedmph").
# Covers the labels TrackMan / Foresight / Garmin / GSPro / Awesome Golf exports use, so
# a player can drop their own session in without renaming a column. Imperial units are
# assumed (mph / yards / rpm / degrees - the common schema's, and the US default).
_HEADER_ALIASES = {
    # already common-schema (identity - so a conformed file passes straight through)
    "shotid": "shot_id",
    "source": "source",
    "player": "player",
    "club": "club",
    "sessiondate": "session_date",
    "ballspeedmph": "ball_speed_mph",
    "clubspeedmph": "club_speed_mph",
    "smashfactor": "smash_factor",
    "launchangledeg": "launch_angle_deg",
    "spinraterpm": "spin_rate_rpm",
    "carryyards": "carry_yards",
    "totalyards": "total_yards",
    "sidedispersion": "side_dispersion",
    "spinaxisdeg": "spin_axis_deg",
    "launchdirectiondeg": "launch_direction_deg",
    # club
    "clubtype": "club",
    "clubname": "club",
    # ball / club speed
    "ballspeed": "ball_speed_mph",
    "clubspeed": "club_speed_mph",
    "clubheadspeed": "club_speed_mph",
    "smash": "smash_factor",
    # launch angle (vertical)
    "launchangle": "launch_angle_deg",
    "launchv": "launch_angle_deg",
    "verticallaunchangle": "launch_angle_deg",
    "launchanglevertical": "launch_angle_deg",
    "vla": "launch_angle_deg",
    # spin
    "spinrate": "spin_rate_rpm",
    "spin": "spin_rate_rpm",
    "totalspin": "spin_rate_rpm",
    "backspin": "spin_rate_rpm",
    # carry / total
    "carry": "carry_yards",
    "carrydistance": "carry_yards",
    "carrydist": "carry_yards",
    "total": "total_yards",
    "totaldistance": "total_yards",
    "totaldist": "total_yards",
    # side / lateral
    "side": "side_dispersion",
    "sidecarry": "side_dispersion",
    "carryside": "side_dispersion",
    "lateral": "side_dispersion",
    "sidetotal": "side_dispersion",
    "offline": "side_dispersion",
    # shape
    "spinaxis": "spin_axis_deg",
    "axis": "spin_axis_deg",
    "launchdirection": "launch_direction_deg",
    "launchh": "launch_direction_deg",
    "horizontallaunchangle": "launch_direction_deg",
    "hla": "launch_direction_deg",
    "azimuth": "launch_direction_deg",
    "launchdir": "launch_direction_deg",
    # meta
    "date": "session_date",
    "name": "player",
    "playername": "player",
}


def _norm_header(h: str) -> str:
    return "".join(ch for ch in str(h).lower() if ch.isalnum())


def conform_export(rows: list[dict]) -> list[dict]:
    """Map a raw launch-monitor export's headers onto the common schema.

    A player's own TrackMan/Foresight/Garmin/GSPro export uses labels like "Ball
    Speed", "Carry", "Spin Rate" - not the common-schema names. This renames the
    columns it recognises (case- and punctuation-insensitively) and drops the rest,
    so a raw session drops straight in. An already-conformed file is unchanged (its
    headers map to themselves). Units are assumed imperial (the common schema's)."""
    out = []
    for r in rows:
        mapped: dict = {}
        for key, value in r.items():
            field = _HEADER_ALIASES.get(_norm_header(key))
            if field and not mapped.get(field):  # first non-empty wins on duplicates
                mapped[field] = value
        out.append(mapped)
    return out


# A player's short game / putting skill, as the factor that scales the strokes they
# need to hole out from around and on the green *above* the tour benchmark (see
# `scoring.expected_strokes_array`): 0 plays the tour curve, higher means more chips
# and putts to get down. The full swing is owned by the bag's dispersion; this is
# only the around-the-green skill the dispersion model can't see.
SHORT_GAME_LEVELS: dict[str, float] = {"Tour": 0.0, "Sharp": 0.12, "Average": 0.25, "Loose": 0.40}


@dataclass(frozen=True)
class PlayerProfile:
    """A named player: which tour bag, scaled how far, at what consistency."""

    name: str
    tour: str  # "pga" / "lpga" - the launch profile to scale from
    dist_scale: float  # 1.0 = tour distance; <1 = slower swing, shorter
    skill: str  # base dispersion preset (tour / scratch / amateur)
    short_game: str = "Average"  # a key of SHORT_GAME_LEVELS (around-the-green skill)


# Driver carries land near: pro ~282, long-am ~258, mid ~234, senior ~209.
PROFILES: dict[str, PlayerProfile] = {
    p.name: p
    for p in (
        PlayerProfile("PGA tour pro", "pga", 1.00, "tour", "Tour"),
        PlayerProfile("Long amateur", "pga", 0.92, "scratch", "Sharp"),
        PlayerProfile("Mid handicap", "pga", 0.83, "scratch", "Average"),
        PlayerProfile("Senior", "pga", 0.74, "amateur", "Average"),
        PlayerProfile("LPGA tour", "lpga", 1.00, "tour", "Tour"),
    )
}


def profile_bag(name: str, *, spread_mult: float = 1.0, seed: int = 0) -> ClubBag:
    """Build a profile's `ClubBag` (its distances + dispersion). `spread_mult`
    tightens/loosens the profile's base consistency on top."""
    p = PROFILES[name]
    skill = skill_from_name(p.skill).scaled(spread_mult)
    return synthetic_bag(p.tour, skill, dist_scale=p.dist_scale, seed=seed)


def _drop_mishits(shots: list) -> list:
    """Drop gross mishits so a club's dispersion reflects normal strikes.

    Real launch-monitor logs are full of duds - whiffs, tops, warm-ups, the odd
    chip logged under the wrong club - and a single 5-yard "drive" wrecks a fitted
    distribution. Keep shots whose ball speed sits within ±30% of the club's
    *median* (robust to the junk that contaminates the mean), so a slow amateur's
    real spread survives but the non-shots don't.
    """
    if len(shots) < MIN_SHOTS:
        return shots
    med = median(s.ball_speed_ms for s in shots)
    lo, hi = 0.7 * med, 1.3 * med
    return [s for s in shots if lo <= s.ball_speed_ms <= hi]


def bag_from_shots(rows: list[dict], *, player: str = "You") -> tuple[ClubBag, set[str]]:
    """Build a real `ClubBag` from a player's own shots (common-schema rows).

    A club with enough *clean* shots gets its real measured dispersion (mishits
    trimmed, distances anchored to its measured carries); clubs the player is short
    on are gap-filled from the tour bag scaled to their measured distances (so the
    planner has a full driver-through-wedge set). Returns the bag and the set of
    clubs that are *real* (the rest are inferred - flag them for honesty).
    """
    calib = calibrate_engine()
    by_club: dict[str, list] = defaultdict(list)
    for r in rows:
        shot = from_fct_row(r)
        if shot is not None:
            by_club[_norm_club(str(r.get("club", "")))].append(shot)

    real: dict[str, ClubStats] = {}
    for club, shots in by_club.items():
        shots = _drop_mishits(shots)
        if len(shots) < MIN_SHOTS:
            continue
        disp = simulate_dispersion(
            shots,
            source="upload",
            player=player,
            club=club,
            cd=calib.cd,
            cl_coeff=calib.cl,
            cd_spin=calib.cd_spin,
        )
        # Anchor the cloud to the player's *measured* carry. The physics gives the
        # dispersion shape (spread, lateral, the launch correlations); the monitor
        # gives the truth of how far they actually hit it. The engine is calibrated
        # on the tour bag, so a given player's simulated mean can sit a few yards off
        # their real one - recentre to the measured mean so the caddie's numbers are
        # *their* numbers, keeping the physics-derived scatter around them.
        measured = [s.measured_carry_yards for s in shots if s.measured_carry_yards is not None]
        carry_mean = median(measured) if measured else disp.carry_mean_yards
        disp = _anchor_carry(disp, carry_mean)
        real[club] = ClubStats(disp, carry_mean, disp.carry_std_yards, disp.lateral_std_yards)

    # Scale the tour bag to this player so the inferred clubs sit at their distances.
    tour = {c.club: c.carry_yards for c in load_trackman_pga()}
    ratios = [real[c].measured_carry_mean / tour[c] for c in real if tour.get(c)]
    scale = median(ratios) if ratios else 1.0
    base = synthetic_bag("pga", SCRATCH, dist_scale=scale)

    clubs = [real.get(cs.dispersion.club, cs) for cs in base.clubs]
    clubs.sort(key=lambda s: s.dispersion.carry_mean_yards, reverse=True)
    bag = ClubBag(
        source="upload", player=player, cd=calib.cd, cl=calib.cl, cd_spin=calib.cd_spin, clubs=clubs
    )
    return bag, set(real)


def load_player_csv(data: str | bytes) -> tuple[ClubBag, set[str]]:
    """Parse a launch-monitor CSV (text or bytes) into a real `ClubBag`.

    Headers are conformed (`conform_export`), so a raw TrackMan/Foresight/Garmin
    export works without renaming columns - not just the strict common schema."""
    text = data.decode("utf-8", "ignore") if isinstance(data, bytes) else data
    return bag_from_shots(conform_export(list(csv.DictReader(io.StringIO(text)))))


def bag_from_warehouse(bq, source: str, player: str) -> tuple[ClubBag, set[str]]:
    """Build a real `ClubBag` from a player's *ingested* shots in gold `fct_shots`.

    The same accurate path as an upload - real per-club dispersion flown from their
    own launch data, gap-filled where they're short, anchored to their measured
    carries - but sourced from the warehouse the pipeline already lands their
    TrackMan/Foresight data in. `bq` is a `warehouse.client()`; this is the seam
    where the data pipeline and the strategy engine meet into a personal caddie.
    """
    from . import warehouse  # lazy: keeps BigQuery optional for everything else

    rows = warehouse.fetch_player_rows(bq, source, player)
    return bag_from_shots(rows, player=player)


def profile_tour_clubs(name: str) -> list[TourClub]:
    """The profile's per-club stock shots (tour averages scaled to its distance) -
    what the conditions adjuster flies to size the wind/density effect for *this*
    player, and what the single-shot view shows."""
    p = PROFILES[name]
    return [
        replace(
            c,
            ball_speed_mph=c.ball_speed_mph * p.dist_scale,
            carry_yards=c.carry_yards * p.dist_scale,
        )
        for c in _TABLES[p.tour]()
    ]


def stock_clubs_for(bag: ClubBag) -> list[TourClub]:
    """Per-club stock shots scaled to *this bag's* measured carries - what the wind
    adjuster flies. Works for any bag (a profile or an uploaded real one)."""
    tour = {c.club: c for c in load_trackman_pga()}
    out = []
    for cs in bag.clubs:
        tc = tour.get(cs.dispersion.club)
        if tc is None or not tc.carry_yards:
            continue
        scale = cs.measured_carry_mean / tc.carry_yards
        out.append(
            replace(
                tc, ball_speed_mph=tc.ball_speed_mph * scale, carry_yards=cs.measured_carry_mean
            )
        )
    return out

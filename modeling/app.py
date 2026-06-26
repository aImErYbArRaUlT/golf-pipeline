"""Interactive strategy engine (Stage F) - a Streamlit app over the whole engine.

Pick a player (a profile, or upload your own shots), your handedness + stock shape,
a tee set and conditions, and see it live on the real course: the bag's dispersion,
Torrey Pines South replanned per hole, the whole round (all 18 vs par), **where to
aim** a given approach at a placed pin, and what wind/altitude do to a shot. No
warehouse or credentials.

Run via `just app` (needs the `app` group).
"""

from __future__ import annotations

import os
from dataclasses import replace

import streamlit as st

# Absolute imports: `streamlit run modeling/app.py` runs this as a top-level
# script (no parent package), so relative imports would fail. The package is
# installed editable, so `modeling` resolves.
from modeling import viz
from modeling.aim import aim_for_pin, clamp_pin_to_green
from modeling.bag import ClubBag
from modeling.benchmarks import calibrate_engine
from modeling.conditions import (
    adjust_bag_for_conditions,
    air_density,
    relative_wind,
    wind_vector,
)
from modeling.course import TEE_LEVELS, load_course
from modeling.physics import simulate
from modeling.planner import SHAPE_SKEW, plan_hole
from modeling.players import (
    PROFILES,
    SHORT_GAME_LEVELS,
    load_player_csv,
    profile_bag,
    stock_clubs_for,
)

_ART = "modeling/artifacts"

# A bag's identity for the plan caches: who, and each club's carry + spreads. Lets
# a profile bag and an uploaded real bag flow through the same cached functions.
_BAG_HASH = {
    ClubBag: lambda b: (
        b.player,
        b.source,
        tuple(
            (
                round(c.dispersion.carry_mean_yards, 1),
                round(c.dispersion.carry_std_yards, 2),
                round(c.dispersion.lateral_std_yards, 2),
            )
            for c in b.clubs
        ),
    )
}


@st.cache_data(show_spinner=False)
def _bag(player: str, consistency: float):
    return profile_bag(player, spread_mult=consistency)


@st.cache_data(show_spinner=False)
def _uploaded(data: bytes):
    """Build a real bag (and which clubs are real) from an uploaded CSV."""
    return load_player_csv(data)


@st.cache_data(show_spinner=False)
def _warehouse_players():
    """(players, error): the gold players an engine bag can be built for (richest
    first), or an error string if the warehouse can't be reached. BigQuery is
    imported lazily and any auth/connection failure is surfaced, not raised, so the
    app still runs without credentials."""
    try:
        from modeling import warehouse

        return warehouse.list_player_bags(warehouse.client()), None
    except Exception as e:  # noqa: BLE001 - show any auth/connection failure in the UI
        return [], str(e)


@st.cache_data(show_spinner=False)
def _warehouse_bag(source: str, player: str):
    """Build a real bag from a player's ingested gold shots (same path as an upload)."""
    from modeling import warehouse
    from modeling.players import bag_from_warehouse

    return bag_from_warehouse(warehouse.client(), source, player)


@st.cache_resource(show_spinner=False)
def _course():
    return load_course("torrey_pines_south")


@st.cache_data(show_spinner=False, hash_funcs=_BAG_HASH)
def _aim(bag, ref: int, fb: float, lr: float, dist: int, short_game: float):
    """Optimal approach aim for a pin placed at (front-back, left-right) on the green."""
    h = _course()[ref - 1]
    gx0, gy0, gx1, gy1 = h.green.bounds  # (downrange0, lateral0, downrange1, lateral1)
    pin = clamp_pin_to_green(h.green, (gx0 + fb * (gx1 - gx0), gy0 + lr * (gy1 - gy0)))
    return aim_for_pin(h, bag, pin, dist, short_game=short_game), pin


@st.cache_data(show_spinner=False, hash_funcs=_BAG_HASH)
def _course_plan(bag, ref: int, tee: str, skew: float, shape: str, short_game: float):
    h = _course()[ref - 1]
    tb = h.tee_for(tee)
    return plan_hole(
        h,
        bag,
        cell_size=5.0,
        tee_xy=(tb.downrange, tb.lateral),
        skew=skew,
        shape=shape,
        short_game=short_game,
    )


@st.cache_data(show_spinner=False, hash_funcs=_BAG_HASH)
def _cond_bag(bag, w_speed: int, w_from: int, temp: int, alt: int, bearing: float):
    """The calm bag shifted for wind + air density (the fast delta-model).

    `w_from` is a compass direction; the wind is resolved into this hole's frame by
    its `bearing`, so the same wind is a headwind on some holes and a tailwind on
    others. The stock shots are the player's own (scaled), so wind sizing fits them.
    """
    return adjust_bag_for_conditions(
        bag,
        stock_clubs_for(bag),
        wind=relative_wind(w_speed, w_from, bearing),
        density=air_density(temp, alt),
    )


@st.cache_data(show_spinner=False, hash_funcs=_BAG_HASH)
def _cond_course_plan(
    bag,
    ref: int,
    w_speed: int,
    w_from: int,
    temp: int,
    alt: int,
    tee: str,
    skew: float,
    shape: str,
    short_game: float,
):
    h = _course()[ref - 1]
    tb = h.tee_for(tee)
    cbag = _cond_bag(bag, w_speed, w_from, temp, alt, h.bearing_deg)
    return plan_hole(
        h,
        cbag,
        cell_size=5.0,
        tee_xy=(tb.downrange, tb.lateral),
        skew=skew,
        shape=shape,
        short_game=short_game,
    )


@st.cache_data(show_spinner=False, hash_funcs=_BAG_HASH)
def _round_rows(
    bag,
    w_speed: int,
    w_from: int,
    temp: int,
    alt: int,
    tee: str,
    skew: float,
    shape: str,
    short_game: float,
):
    """One summary row per hole - holes are independent, so a round is their sum.

    Reuses the per-hole plan cache, so a hole already viewed costs nothing here.
    """
    rows = []
    for h in _course():
        p = _cond_course_plan(bag, h.ref, w_speed, w_from, temp, alt, tee, skew, shape, short_game)
        rows.append(
            {
                "Hole": h.ref,
                "Par": h.par,
                "Yards": round(h.tee_for(tee).yards),
                "Expected": round(p.tee_value, 2),
                "vs par": round(p.tee_value - h.par, 2),
                "Shots": len(p.shots),
                "Plan": " → ".join(f"{s.club} ({s.shape})" for s in p.shots),
            }
        )
    return rows


def _elev_note(hole, tee) -> str | None:
    """How a hole's green sits vs the chosen tee, and the elevation-adjusted yardage."""
    if not hole.elevation:
        return None
    tb = hole.tee_for(tee)
    net = float(hole.elevation_at([hole.pin_distance_yards])[0]) - float(
        hole.elevation_at([tb.downrange])[0]
    )
    plays = tb.yards + 0.93 * net  # uphill plays longer
    if abs(net) < 2.0:
        return f"Terrain: green is level with this tee - plays its {tb.yards:.0f} yds."
    updown = "uphill" if net > 0 else "downhill"
    return f"Terrain: green is **{abs(net):.0f} yds {updown}** - plays like ~{plays:.0f} yds."


def _slope_desc(slope) -> str | None:
    """Which way a green falls, in words - what makes the aim sit below the hole."""
    a, b = slope
    mag = (a * a + b * b) ** 0.5
    if mag < 0.005:
        return None
    parts = []
    if abs(a) > 0.3 * mag:
        parts.append("back" if -a > 0 else "front")
    if abs(b) > 0.3 * mag:
        parts.append("right" if -b > 0 else "left")
    where = "-".join(parts) or "gently"
    return f"Green falls **{where}** ({mag * 100:.0f}%) - aim leaves an uphill putt below the hole."


def _player_skew(hand: str, shape: str) -> tuple[float, str]:
    """(skew, label) for a player's stock shape. A right-hander's draw curves
    right-to-left; a left-hander's is mirrored - so flip the skew for a lefty."""
    if shape == "Straight":
        return 0.0, "straight"
    base = SHAPE_SKEW[shape.lower()]  # draw -, fade + (right-handed)
    return (base if hand == "Right" else -base), shape.lower()


def _wind_desc(speed: int, w_from: int, bearing: float) -> str:
    """Plain words for how a compass wind plays on a hole of the given bearing."""
    if speed == 0:
        return "calm"
    import math

    rel = math.radians((w_from - bearing) % 360.0)
    into, right = math.cos(rel), math.sin(rel)  # +into / +from the right
    head = "into" if into > 0.35 else "downwind" if into < -0.35 else ""
    side = "off the right" if right > 0.35 else "off the left" if right < -0.35 else ""
    return f"{speed} mph " + (" ".join(p for p in (head, side) if p) or "crosswind")


def main() -> None:
    os.makedirs(_ART, exist_ok=True)
    st.set_page_config(page_title="Golf Strategy Engine", layout="wide")
    st.title("Golf Strategy Engine")
    st.caption(
        "A calibrated ball-flight model → dispersion → strokes-gained scoring → whole-hole plan."
    )

    with st.sidebar:
        st.header("Player")
        mode = st.radio("Data", ["Profile", "My ingested data", "Upload my shots"])
        # Short game is a separate skill: a launch-monitor bag only captures full
        # swings, so chipping/bunkers/putting can't be inferred from it. Default it to
        # the profile's level (set within the branch, where the profile is in scope);
        # the user sets it otherwise.
        sg_default = "Average"
        if mode == "Profile":
            player = st.selectbox("Profile", list(PROFILES), index=0)
            consistency = st.slider("Spread (1 = profile, higher = looser)", 0.6, 4.0, 1.0, 0.2)
            bag, real_clubs = _bag(player, consistency), None
            label = f"{player} (spread x{consistency:g})"
            sg_default = PROFILES[player].short_game
        elif mode == "My ingested data":
            players, err = _warehouse_players()
            if err:
                st.warning(f"Warehouse unavailable - falling back to a profile. ({err[:90]})")
                bag, real_clubs, label = _bag("PGA tour pro", 1.0), None, "warehouse unavailable"
            elif not players:
                st.info("No ingested player has enough launch data for a bag yet.")
                bag, real_clubs, label = _bag("PGA tour pro", 1.0), None, "no warehouse data"
            else:
                opts = {
                    f"{p['source']} · {p['player']}  ({p['clubs']} clubs, {p['shots']:,} shots)": p
                    for p in players
                }
                p = opts[st.selectbox("Ingested player", list(opts))]
                bag, real_clubs = _warehouse_bag(p["source"], p["player"])
                label = f"{p['player']} ({p['source']})"
        else:
            up = st.file_uploader("Launch-monitor CSV (common schema)", type="csv")
            st.caption("Columns: club, ball_speed_mph, launch_angle_deg, spin_rate_rpm, …")
            if up is not None:
                bag, real_clubs = _uploaded(up.getvalue())
                label = "Your shots"
            else:
                bag, real_clubs, label = _bag("PGA tour pro", 1.0), None, "upload to personalise"
        tee_level = st.selectbox("Tees", TEE_LEVELS, index=0)
        c_hand, c_shape = st.columns(2)
        hand = c_hand.selectbox("Hand", ["Right", "Left"], index=0)
        shape_name = c_shape.selectbox("Shot shape", ["Fade", "Draw"], index=0)
        skew, shape = _player_skew(hand, shape_name)
        sg_level = st.selectbox(
            "Short game",
            list(SHORT_GAME_LEVELS),
            index=list(SHORT_GAME_LEVELS).index(sg_default),
            help="Chipping, bunkers and putting around the green. Your bag only sees "
            "full swings, so this is set separately - it scores getting up and down.",
        )
        short_game = SHORT_GAME_LEVELS[sg_level]
        st.header("Conditions")
        w_speed = st.slider("Wind (mph)", 0, 30, 0)
        w_from = st.slider("Wind from (compass °: 0 = N, 90 = E, 180 = S)", 0, 360, 0, 15)
        temp = st.slider("Temperature (°C)", -5, 40, 15)
        alt = st.slider("Altitude (m)", 0, 2500, 0, 100)

    drv = next(
        (c.dispersion.carry_mean_yards for c in bag.clubs if c.dispersion.club == "Driver"), 0
    )
    calm = w_speed == 0 and temp == 15 and alt == 0
    cond_label = "calm" if calm else f"{w_speed} mph wind, {temp}°C, {alt} m"

    bag_tab, course_tab, round_tab, aim_tab, cond_tab = st.tabs(
        ["The bag", "Torrey Pines South", "The round", "Where to aim", "Conditions"]
    )

    with bag_tab:
        st.subheader("Per-club dispersion")
        st.caption(f"{label} - carries the driver about {drv:.0f} yds.")
        if real_clubs is not None:
            measured = ", ".join(sorted(real_clubs)) or "none"
            st.caption(
                f"Built from your shots: **{len(real_clubs)} club(s) measured** ({measured}); "
                "the rest inferred from your distances and flagged. The carries are your "
                "*measured* distances; the ovals are your real shot-to-shot spread."
            )
            stds = [
                cs.dispersion.carry_std_yards
                for cs in bag.clubs
                if cs.dispersion.club in real_clubs
            ]
            if stds:
                avg = sum(stds) / len(stds)
                tail = (
                    " - tour-tight."
                    if avg < 8
                    else (
                        " - wide, so the data is inconsistent or partial-swing; the numbers "
                        "reflect that honestly."
                        if avg > 18
                        else "."
                    )
                )
                st.caption(f"Measured consistency: carries vary about ±{avg:.0f} yds (1σ){tail}")
        shown = [cs.dispersion for cs in bag.clubs[:: max(1, len(bag.clubs) // 6)]][:6]
        viz.plot_dispersion(shown, f"Dispersion - {label}", f"{_ART}/app_bag.png")
        st.image(f"{_ART}/app_bag.png")

    with course_tab:
        st.subheader("Torrey Pines South - real hole outlines (OpenStreetMap)")
        holes = _course()

        def _hole_label(r: int) -> str:
            h = holes[r - 1]
            return f"{r} · par {h.par} · {h.tee_for(tee_level).yards:.0f}y"

        ref = st.select_slider(
            "Hole", options=[h.ref for h in holes], value=18, format_func=_hole_label
        )
        c_hole = holes[ref - 1]
        c_bag = _cond_bag(bag, w_speed, w_from, temp, alt, c_hole.bearing_deg)
        c_plan = _cond_course_plan(
            bag, ref, w_speed, w_from, temp, alt, tee_level, skew, shape, short_game
        )
        hole_wind = _wind_desc(w_speed, w_from, c_hole.bearing_deg)
        delta = (
            c_plan.tee_value - _course_plan(bag, ref, tee_level, skew, shape, short_game).tee_value
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("Par", c_hole.par)
        c2.metric("Yards", f"{c_hole.tee_for(tee_level).yards:.0f}", help=f"{tee_level} tee")
        c3.metric(
            "Expected score",
            f"{c_plan.tee_value:.2f}",
            None if calm else f"{delta:+.2f} vs calm",
            delta_color="inverse",
        )
        st.caption(
            f"Conditions: {cond_label} - plays as **{hole_wind}** on this hole "
            f"(bearing {c_hole.bearing_deg:.0f}°). Replanned live, the whole hole."
        )
        elev_note = _elev_note(c_hole, tee_level)
        if elev_note:
            st.caption(elev_note)
        for i, s in enumerate(c_plan.shots, 1):
            st.write(f"{i}. **{s.club}** ({s.shape}) → aim ({s.aim_x:.0f}, {s.aim_y:+.0f})")
        st.write(f"then chip + putt: {c_plan.finish_strokes:.2f}")
        viz.plot_course_plan(
            c_hole,
            c_plan,
            c_bag,
            f"{c_hole.label} - {label}, {cond_label}",
            f"{_ART}/app_course.png",
            skew=skew,
        )
        st.image(f"{_ART}/app_course.png")

    with round_tab:
        st.subheader("The whole round - all 18 holes")
        with st.spinner("Planning all 18 holes…"):
            rows = _round_rows(bag, w_speed, w_from, temp, alt, tee_level, skew, shape, short_game)
        par = sum(r["Par"] for r in rows)
        total = sum(r["Expected"] for r in rows)
        yards = sum(r["Yards"] for r in rows)
        front = sum(r["Expected"] for r in rows[:9])
        back = sum(r["Expected"] for r in rows[9:])
        c1, c2, c3 = st.columns(3)
        c1.metric(
            f"Expected round (par {par})",
            f"{total:.1f}",
            f"{total - par:+.1f} vs par",
            delta_color="inverse",
        )
        c2.metric("Front 9", f"{front:.1f}", f"{front - sum(r['Par'] for r in rows[:9]):+.1f}")
        c3.metric("Back 9", f"{back:.1f}", f"{back - sum(r['Par'] for r in rows[9:]):+.1f}")
        st.caption(
            f"{label} · {tee_level} tees ({yards:,} yds) · {sg_level} short game · {cond_label}. "
            "Each hole is planned independently (tee → holed); the round is their sum. Move up a "
            "tee set, change the wind (a fixed compass direction - it helps downwind holes, hurts "
            "into-wind), or drop the short game and watch the round move."
        )
        st.dataframe(rows, use_container_width=True, hide_index=True)

    with aim_tab:
        st.subheader("Where to aim - your dispersion vs the flag")
        holes = _course()
        aref = st.select_slider(
            "Hole",
            options=[h.ref for h in holes],
            value=18,
            key="aim_hole",
            format_func=lambda r: f"{r} · par {holes[r - 1].par}",
        )
        ah = holes[aref - 1]
        cc = st.columns(3)
        fb = cc[0].slider("Pin front ↔ back", 0.0, 1.0, 0.5, 0.1)
        lr = cc[1].slider("Pin left ↔ right", 0.0, 1.0, 0.5, 0.1)
        dist = cc[2].slider("Approach (yds)", 70, 200, 150, 5)
        advice, pin = _aim(bag, aref, fb, lr, dist, short_game)
        ls = f"{abs(advice.long_yds):.0f} yds " + ("long" if advice.long_yds >= 0 else "short")
        rs = f"{abs(advice.right_yds):.0f} yds " + ("right" if advice.right_yds >= 0 else "left")
        if abs(advice.long_yds) < 1.5 and abs(advice.right_yds) < 1.5:
            st.markdown(f"### Aim at the flag with your **{advice.club}**.")
        else:
            st.markdown(f"### Aim **{ls}, {rs}** of the flag with your **{advice.club}**.")
        c1, c2, c3 = st.columns(3)
        c1.metric("Finds the green", f"{advice.on_green_pct:.0f}%")
        c2.metric("Proximity", f"{advice.proximity_ft:.0f} ft")
        c3.metric("Expected to hole out", f"{advice.expected:.2f}")
        slope_note = _slope_desc(ah.green_slope)
        if slope_note:
            st.caption(slope_note)
        viz.plot_aim(
            ah, bag, pin, advice, f"{ah.label} - aim from {dist}y · {label}", f"{_ART}/app_aim.png"
        )
        st.image(f"{_ART}/app_aim.png")

    with cond_tab:
        st.subheader("What the sidebar conditions do to one shot")
        st.caption(
            f"Set wind / temperature / altitude in the sidebar. Now: {cond_label}. "
            "This demo shot faces due north, so the compass wind applies directly."
        )
        stock = stock_clubs_for(bag)
        club = st.selectbox("Club", [c.club for c in stock])
        cal = calibrate_engine()
        tc = next(c for c in stock if c.club == club)
        base = tc.to_shot_input()
        calm_shot = simulate(base, cal.cd, cal.cl, cal.cd_spin)
        cond_shot = simulate(
            replace(base, air_density=air_density(temp, alt)),
            cal.cd,
            cal.cl,
            cal.cd_spin,
            wind=wind_vector(w_speed, w_from),
        )
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Carry",
            f"{cond_shot.carry_yards:.0f} yds",
            f"{cond_shot.carry_yards - calm_shot.carry_yards:+.0f} vs calm",
        )
        c2.metric(
            "Total",
            f"{cond_shot.total_yards:.0f} yds",
            f"{cond_shot.total_yards - calm_shot.total_yards:+.0f}",
        )
        c3.metric(
            "Sideways",
            f"{cond_shot.lateral_yards:+.0f} yds",
            f"{cond_shot.lateral_yards - calm_shot.lateral_yards:+.0f}",
        )
        viz.plot_trajectory(cond_shot, f"{club} - {cond_label}", f"{_ART}/app_traj.png")
        st.image(f"{_ART}/app_traj.png")


if __name__ == "__main__":
    main()

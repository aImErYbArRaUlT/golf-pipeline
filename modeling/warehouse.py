"""The modeling package's one connection to gold `fct_shots`.

The physics core and calibration are pure (no warehouse). This module is the
single place that talks to BigQuery, so the runners share one client, one column
list, and the driver-band filter used as an independent radar check.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from google.cloud import bigquery

from .calibration import mean_abs_carry_error
from .contracts import ShotInput, from_fct_row
from .dispersion import MIN_SHOTS

load_dotenv()

# Launch inputs + measured carry + grouping keys - everything a ShotInput needs,
# plus player/source/club for grouping and side_dispersion for validating the
# simulated lateral spread against what the monitor itself reported.
_COLS = (
    "ball_speed_mph, launch_angle_deg, spin_rate_rpm, "
    "spin_axis_deg, launch_direction_deg, carry_yards, side_dispersion, "
    "source, player, club"
)

# TrackMan radar is the only genuinely-measured carry in the warehouse. The bag
# is calibrated elsewhere (on the TrackMan tour averages); this driver band is an
# independent check - does the calibrated engine reproduce our own measured driver
# carry? The 1-in-20 fingerprint sample keeps it fast and reproducible.
DRIVER_BAND = """
source = 'trackman' and carry_method = 'measured'
  and carry_yards is not null
  and ball_speed_mph between 130 and 175
  and spin_rate_rpm between 1500 and 4000
  and launch_angle_deg between 7 and 18
  and mod(abs(farm_fingerprint(shot_id)), 20) = 0
"""

# Shots usable for dispersion: the three launch inputs the engine requires.
HAS_LAUNCH_INPUTS = (
    "ball_speed_mph is not null and launch_angle_deg is not null and spin_rate_rpm is not null"
)


def client() -> bigquery.Client:
    """A BigQuery client for the active project (ADC auth)."""
    return bigquery.Client(
        project=os.environ["GCP_PROJECT_ID"],
        location=os.environ.get("GCP_LOCATION", "EU"),
    )


def fetch_rows(bq: bigquery.Client, where: str) -> list[dict]:
    """Raw `fct_shots` rows (as dicts) matching a WHERE clause, current env."""
    project = os.environ["GCP_PROJECT_ID"]
    env = os.environ.get("GOLF_ENV", "dev")
    sql = f"select {_COLS} from `{project}.{env}_gold.fct_shots` where {where}"
    return [dict(r) for r in bq.query(sql).result()]


def list_player_bags(bq: bigquery.Client) -> list[dict]:
    """Every (source, player) in gold a real bag can be built for, richest first.

    For each, how many clubs clear the dispersion threshold (`MIN_SHOTS`) and the
    total launch-rich shots - the menu the app offers. A player with no club over
    the threshold (e.g. camera-only sources with no launch data) drops out, since
    nothing physics-real can be fit from them.
    """
    project = os.environ["GCP_PROJECT_ID"]
    env = os.environ.get("GOLF_ENV", "dev")
    sql = f"""
        select source, player,
               countif(club_shots >= {MIN_SHOTS}) as clubs,
               sum(club_shots) as shots
        from (
            select source, player, club, count(*) as club_shots
            from `{project}.{env}_gold.fct_shots`
            where {HAS_LAUNCH_INPUTS}
            group by source, player, club
        )
        group by source, player
        having clubs >= 1
        order by clubs desc, shots desc
    """
    return [dict(r) for r in bq.query(sql).result()]


def fetch_player_rows(bq: bigquery.Client, source: str, player: str) -> list[dict]:
    """One player's launch-rich `fct_shots` rows (parameterised - source/player are
    chosen from the warehouse's own values, but bind them rather than interpolate)."""
    project = os.environ["GCP_PROJECT_ID"]
    env = os.environ.get("GOLF_ENV", "dev")
    sql = (
        f"select {_COLS} from `{project}.{env}_gold.fct_shots` "
        f"where {HAS_LAUNCH_INPUTS} and source = @source and player = @player"
    )
    cfg = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("source", "STRING", source),
            bigquery.ScalarQueryParameter("player", "STRING", player),
        ]
    )
    return [dict(r) for r in bq.query(sql, job_config=cfg).result()]


def fetch_shots(bq: bigquery.Client, where: str) -> list[ShotInput]:
    """SI-unit ShotInputs for rows matching a WHERE clause (unmappable rows dropped)."""
    return [s for s in (from_fct_row(r) for r in fetch_rows(bq, where)) if s is not None]


def driver_radar_check(
    bq: bigquery.Client, cd: float, cl: float, cd_spin: float
) -> tuple[float, int]:
    """Independent check: carry MAE of the calibrated engine on measured driver radar.

    Returns (mean abs carry error in yards, number of shots).
    """
    shots = fetch_shots(bq, DRIVER_BAND)
    return mean_abs_carry_error(shots, cd, cl, cd_spin), len(shots)

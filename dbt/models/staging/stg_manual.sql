-- Manual / personal sessions -> common schema.
-- The "manual" source is a player's own launch-monitor session, landed locally
-- via `just ingest-session` rather than fetched from a URL. Its raw columns are
-- already the common-schema names (the ingest step conforms a TrackMan/Foresight/
-- Garmin export to them before landing), so this model only types the strings,
-- hashes shot_id, and applies the same null-cleaning as every other source.
--
-- manual_raw only exists once a session has been ingested, so the source is
-- optional: if the table isn't there yet, emit an empty (correctly-typed) result
-- so `dbt run` works for everyone, ingested session or not. That runtime guard uses
-- adapter.get_relation / env_var, which sqlfluff's static templater can't render, so
-- this model is excluded from sqlfluff (see .pre-commit-config.yaml) and gated by the
-- dbt build + data tests instead.

{% set bronze = target.name ~ '_bronze' %}
{% set rel = none %}
{% if execute %}
    {% set rel = adapter.get_relation(
        database=env_var('GCP_PROJECT_ID'), schema=bronze, identifier='manual_raw'
    ) %}
{% endif %}

with raw as (
{% if rel %}
    select * from {{ rel }}
{% else %}
    -- No session ingested yet: a zero-row frame with the columns `typed` reads
    -- (BigQuery rejects a WHERE without a FROM, hence `from unnest([1])`).
    select
        cast(null as string) as _source,
        cast(null as string) as _row_index,
        cast(null as string) as player,
        cast(null as string) as club,
        cast(null as string) as session_date,
        cast(null as string) as ball_speed_mph,
        cast(null as string) as club_speed_mph,
        cast(null as string) as smash_factor,
        cast(null as string) as launch_angle_deg,
        cast(null as string) as spin_rate_rpm,
        cast(null as string) as carry_yards,
        cast(null as string) as total_yards,
        cast(null as string) as side_dispersion,
        cast(null as string) as spin_axis_deg,
        cast(null as string) as launch_direction_deg
    from unnest([1])
    where false
{% endif %}
),

typed as (
    select
        to_hex(md5(concat(_source, '-', cast(_row_index as string)))) as shot_id,
        _source as source,
        nullif(player, '') as player,
        club,
        -- Conformed sessions carry an ISO date when the export had one, else blank.
        safe.parse_date('%Y-%m-%d', nullif(session_date, '')) as session_date,
        safe_cast(ball_speed_mph as float64) as ball_speed_mph,
        safe_cast(club_speed_mph as float64) as club_speed_mph,
        safe_cast(smash_factor as float64) as smash_factor,
        safe_cast(launch_angle_deg as float64) as launch_angle_deg,
        safe_cast(spin_rate_rpm as float64) as spin_rate_rpm,
        safe_cast(carry_yards as float64) as carry_yards,
        safe_cast(total_yards as float64) as total_yards,
        safe_cast(side_dispersion as float64) as side_dispersion,
        safe_cast(spin_axis_deg as float64) as spin_axis_deg,
        safe_cast(launch_direction_deg as float64) as launch_direction_deg
    from raw
)

select
    shot_id,
    source,
    player,
    club,
    session_date,
    if(is_nan(ball_speed_mph), null, ball_speed_mph) as ball_speed_mph,
    if(is_nan(club_speed_mph), null, club_speed_mph) as club_speed_mph,
    if(is_nan(smash_factor), null, smash_factor) as smash_factor,
    if(is_nan(launch_angle_deg), null, launch_angle_deg) as launch_angle_deg,
    if(is_nan(spin_rate_rpm) or spin_rate_rpm < 0, null, spin_rate_rpm) as spin_rate_rpm,
    if(is_nan(carry_yards), null, carry_yards) as carry_yards,
    if(is_nan(total_yards), null, total_yards) as total_yards,
    if(is_nan(side_dispersion), null, side_dispersion) as side_dispersion,
    if(is_nan(spin_axis_deg), null, spin_axis_deg) as spin_axis_deg,
    if(is_nan(launch_direction_deg), null, launch_direction_deg) as launch_direction_deg
from typed

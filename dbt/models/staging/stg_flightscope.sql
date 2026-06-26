-- FlightScope Mevo -> common schema.
-- A fourth monitor type (doppler radar). Units are already imperial, so no
-- conversion - the work here is: derive session_date from the file path (the
-- date lives in the folder name, range/YYYY-MM-DD/...), normalise club codes
-- (6I -> "6 Iron", 3W -> "3 Wood"), and null the fields this export lacks
-- (total distance, dispersion, player).

with raw as (
    select * from {{ source('bronze', 'flightscope_raw') }}
),

typed as (
    select
        to_hex(md5(concat(_source, '-', cast(_row_index as string)))) as shot_id,
        _source as source,
        club as club_code,
        -- the session date is the folder name in the file path
        safe.parse_date(
            '%Y-%m-%d', regexp_extract(_source_file, r'(\d{4}-\d{2}-\d{2})')
        ) as session_date,
        safe_cast(ball_speed_mph as float64) as ball_speed_mph,
        safe_cast(club_speed_mph as float64) as club_speed_mph,
        safe_cast(smash as float64) as smash_factor,
        safe_cast(launch_angle_v as float64) as launch_angle_deg,
        safe_cast(spin_rpm as float64) as spin_rate_rpm,
        safe_cast(carry_distance_yds as float64) as carry_yards
    from raw
)

select
    shot_id,
    source,
    'unknown' as player,                          -- not present in this export
    case
        when club_code = 'Driver' then 'Driver'
        when club_code = 'PW' then 'Pitching Wedge'
        when club_code = 'GW' then 'Gap Wedge'
        when club_code = 'SW' then 'Sand Wedge'
        when club_code = 'LW' then 'Lob Wedge'
        when regexp_contains(club_code, r'^[0-9]+I$')
            then concat(regexp_extract(club_code, r'^([0-9]+)I$'), ' Iron')
        when regexp_contains(club_code, r'^[0-9]+W$')
            then concat(regexp_extract(club_code, r'^([0-9]+)W$'), ' Wood')
        else club_code
    end as club,
    session_date,
    if(is_nan(ball_speed_mph), null, ball_speed_mph) as ball_speed_mph,
    if(is_nan(club_speed_mph), null, club_speed_mph) as club_speed_mph,
    if(is_nan(smash_factor), null, smash_factor) as smash_factor,
    if(is_nan(launch_angle_deg), null, launch_angle_deg) as launch_angle_deg,
    if(is_nan(spin_rate_rpm) or spin_rate_rpm < 0, null, spin_rate_rpm) as spin_rate_rpm,
    if(is_nan(carry_yards), null, carry_yards) as carry_yards,
    cast(null as float64) as total_yards,         -- not present in this export
    cast(null as float64) as side_dispersion,     -- not present in this export
    cast(null as float64) as spin_axis_deg,       -- base Mevo doesn't report it
    cast(null as float64) as launch_direction_deg -- base Mevo doesn't report it
from typed

-- TrackMan -> common schema.
-- Bronze lands every column as a string; here we type it, rename to the
-- common names, and clean known bad values. Units are already mph/deg/rpm/
-- yards in the TrackMan export, so no conversion is needed (unit conversion
-- shows up with the metric-based source in Phase 3). TrackMan exports carry
-- no player or session date, so those are defaulted.

with raw as (
    select * from {{ source('bronze', 'trackman_raw') }}
),

-- Type the raw strings. safe_cast makes unparseable values null; BigQuery
-- parses the literal 'NaN' into a float NaN, scrubbed to null in the output.
typed as (
    select
        to_hex(md5(concat(_source, '-', cast(_row_index as string)))) as shot_id,
        _source as source,
        club,
        safe_cast(ball_speed as float64) as ball_speed_mph,
        safe_cast(club_speed as float64) as club_speed_mph,
        safe_cast(smash_factor as float64) as smash_factor,
        safe_cast(launch_angle as float64) as launch_angle_deg,
        safe_cast(spin_rate as float64) as spin_rate_rpm,
        safe_cast(carry_flat_length as float64) as carry_yards,
        safe_cast(total as float64) as total_yards,
        safe_cast(side_total as float64) as side_dispersion,
        safe_cast(spin_axis as float64) as spin_axis_deg,
        safe_cast(launch_direction as float64) as launch_direction_deg
    from raw
)

select
    shot_id,
    source,
    'unknown' as player,                   -- not present in TrackMan export
    club,
    cast(null as date) as session_date,    -- not present in TrackMan export
    if(is_nan(ball_speed_mph), null, ball_speed_mph) as ball_speed_mph,
    if(is_nan(club_speed_mph), null, club_speed_mph) as club_speed_mph,
    if(is_nan(smash_factor), null, smash_factor) as smash_factor,
    if(is_nan(launch_angle_deg), null, launch_angle_deg) as launch_angle_deg,
    -- Spin can't be negative; TrackMan uses a large negative sentinel for
    -- "no measurement". Null out both that and NaN.
    if(is_nan(spin_rate_rpm) or spin_rate_rpm < 0, null, spin_rate_rpm) as spin_rate_rpm,
    if(is_nan(carry_yards), null, carry_yards) as carry_yards,
    if(is_nan(total_yards), null, total_yards) as total_yards,
    if(is_nan(side_dispersion), null, side_dispersion) as side_dispersion,
    -- launch shape (for curvature physics): + spin axis = fade, + direction = right
    if(is_nan(spin_axis_deg), null, spin_axis_deg) as spin_axis_deg,
    if(is_nan(launch_direction_deg), null, launch_direction_deg) as launch_direction_deg
from typed

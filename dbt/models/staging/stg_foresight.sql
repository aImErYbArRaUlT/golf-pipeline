-- Foresight/Garmin -> common schema.
-- This is the conforming payoff: a genuinely different export (different
-- column names and order, split backspin/sidespin, weather + swing-tempo
-- fields, and - unlike TrackMan - real player, date, and club type) mapped
-- into the exact same common schema as stg_trackman. Downstream never sees
-- the difference.
--
-- Units in this export are already mph / yards / rpm / deg (same as TrackMan),
-- so no unit conversion is needed here. If a future Foresight export landed in
-- m/s or metres, the conversion would go in this model - staging is the only
-- place units are normalised.

with raw as (
    select * from {{ source('bronze', 'foresight_raw') }}
),

-- Type the raw strings and map Garmin's columns to the common names.
typed as (
    select
        to_hex(md5(concat(_source, '-', cast(_row_index as string)))) as shot_id,
        _source as source,
        player,
        club_type as club,
        -- Garmin stamps a full timestamp like "5/4/26 10:51:29"; keep the date.
        -- Garmin sessions use two timestamp styles: 24-hour ("5/4/26 10:51:29")
        -- and 12-hour with AM/PM ("05/23/26 08:28:38 AM"). Try both.
        date(coalesce(
            safe.parse_timestamp('%m/%d/%y %H:%M:%S', `date`),
            safe.parse_timestamp('%m/%d/%y %I:%M:%S %p', `date`)
        )) as session_date,
        safe_cast(ball_speed as float64) as ball_speed_mph,
        safe_cast(club_speed as float64) as club_speed_mph,
        safe_cast(smash_factor as float64) as smash_factor,
        safe_cast(launch_angle as float64) as launch_angle_deg,
        safe_cast(spin_rate as float64) as spin_rate_rpm,
        safe_cast(carry_distance as float64) as carry_yards,
        safe_cast(total_distance as float64) as total_yards,
        -- Signed lateral offset at landing, matching TrackMan's side_total.
        safe_cast(total_deviation_distance as float64) as side_dispersion,
        safe_cast(spin_axis as float64) as spin_axis_deg,
        safe_cast(launch_direction as float64) as launch_direction_deg
    from raw
)

select
    shot_id,
    source,
    nullif(player, '') as player,
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

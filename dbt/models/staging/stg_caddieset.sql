-- CaddieSet -> common schema.
-- The hardest conform so far, and the one that exercises the whole staging
-- contract:
--   * UNIT CONVERSION (this source is metric): ball speed m/s -> mph,
--     distances m -> yards. This is where the "staging normalizes units"
--     design finally does real work, not just renaming.
--   * DEDUP: each physical shot is captured twice (one row per camera view,
--     FACEON/DTL). We keep one row per shot so analytics don't double-count.
--   * DERIVED metric: there's no single "spin rate" - combine the back/side
--     components into total spin = sqrt(back^2 + side^2).
--   * MISSING fields: this monitor reports no club speed, smash, launch angle,
--     or date; those are nulled and documented (player comes from GolferId).

{% set ms_to_mph = 2.2369362920544 %}
{% set m_to_yards = 1.0936132983377 %}

with raw as (
    select * from {{ source('bronze', 'caddieset_raw') }}
),

cast_layer as (
    select
        _row_index,
        _source,
        golferid,
        clubtype,
        safe_cast(ballspeed as float64) as ballspeed_ms,
        safe_cast(carry as float64) as carry_m,
        safe_cast(distance as float64) as distance_m,
        safe_cast(lrdistanceout as float64) as lr_m,
        safe_cast(spinback as float64) as spinback_rpm,
        safe_cast(spinside as float64) as spinside_rpm,
        safe_cast(spinaxis as float64) as spin_axis_deg,
        safe_cast(directionangle as float64) as launch_direction_deg
    from raw
),

-- Scrub any NaN to null before they propagate through the conversions.
clean as (
    select
        _row_index,
        _source,
        golferid,
        clubtype,
        if(is_nan(ballspeed_ms), null, ballspeed_ms) as ballspeed_ms,
        if(is_nan(carry_m), null, carry_m) as carry_m,
        if(is_nan(distance_m), null, distance_m) as distance_m,
        if(is_nan(lr_m), null, lr_m) as lr_m,
        if(is_nan(spinback_rpm), null, spinback_rpm) as spinback_rpm,
        if(is_nan(spinside_rpm), null, spinside_rpm) as spinside_rpm,
        if(is_nan(spin_axis_deg), null, spin_axis_deg) as spin_axis_deg,
        if(is_nan(launch_direction_deg), null, launch_direction_deg) as launch_direction_deg
    from cast_layer
),

-- One physical shot appears once per camera view; keep a single row. BigQuery
-- can't partition by floats, so fingerprint the shot's physics as a string.
-- Order by _row_index so the kept row (and thus its shot_id) is stable.
fingerprinted as (
    select
        *,
        concat(
            coalesce(cast(golferid as string), ''), '|',
            coalesce(clubtype, ''), '|',
            coalesce(cast(carry_m as string), ''), '|',
            coalesce(cast(distance_m as string), ''), '|',
            coalesce(cast(ballspeed_ms as string), ''), '|',
            coalesce(cast(spinback_rpm as string), ''), '|',
            coalesce(cast(spinside_rpm as string), ''), '|',
            coalesce(cast(lr_m as string), '')
        ) as shot_fingerprint
    from clean
),

deduped as (
    select
        *,
        row_number() over (
            partition by shot_fingerprint order by _row_index
        ) as view_rank
    from fingerprinted
)

select
    to_hex(md5(concat(_source, '-', cast(_row_index as string)))) as shot_id,
    _source as source,
    concat('Golfer ', golferid) as player,
    -- normalise club codes to the same names the other sources use
    case clubtype
        when 'W1' then 'Driver'
        when 'W3' then '3 Wood'
        when 'I4' then '4 Iron'
        when 'I5' then '5 Iron'
        when 'I6' then '6 Iron'
        when 'I7' then '7 Iron'
        when 'I8' then '8 Iron'
        when 'I9' then '9 Iron'
        else clubtype
    end as club,
    cast(null as date) as session_date,             -- not captured by this source
    round(ballspeed_ms * {{ ms_to_mph }}, 2) as ball_speed_mph,
    cast(null as float64) as club_speed_mph,        -- not captured by this source
    cast(null as float64) as smash_factor,          -- needs club speed; not derivable
    cast(null as float64) as launch_angle_deg,      -- not captured by this source
    round(sqrt(pow(spinback_rpm, 2) + pow(spinside_rpm, 2)), 0) as spin_rate_rpm,
    round(carry_m * {{ m_to_yards }}, 1) as carry_yards,
    round(distance_m * {{ m_to_yards }}, 1) as total_yards,
    round(lr_m * {{ m_to_yards }}, 1) as side_dispersion,
    spin_axis_deg,                                -- angles need no unit conversion
    launch_direction_deg
from deduped
where view_rank = 1

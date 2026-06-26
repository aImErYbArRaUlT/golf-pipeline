-- Shot fact. Grain: one row per shot.
-- Resolves three point-in-time dimension keys: the session (per source), and
-- the player and club versions that were valid at the session's date - an
-- as-of join (session_date between valid_from and valid_to). So segmenting by
-- handicap or club setup is historically accurate: a 2024 shot attributes to
-- the 2024 handicap, not today's. club_age is derived from the session year and
-- the club's model year.
with shots as (
    select * from {{ ref('silver_shots') }}
),

sessions as (
    select * from {{ ref('dim_session') }}
),

joined as (
    select
        s.shot_id,
        s.source,
        s.player,
        s.club,
        sess.session_key,
        sess.session_date,
        sess.carry_method,
        -- A player or club not in the seeded dimensions (e.g. a freshly ingested
        -- personal session) falls back to the 'unknown' member, so the keys stay
        -- non-null and the FK relationships hold.
        coalesce(dp.player_key, to_hex(md5('unknown|1900-01-01'))) as player_key,
        coalesce(dc.club_key, to_hex(md5('unknown|unknown|1900-01-01'))) as club_key,
        dc.model_year as club_model_year,
        s.ball_speed_mph,
        s.club_speed_mph,
        s.smash_factor,
        s.launch_angle_deg,
        s.spin_rate_rpm,
        s.carry_yards,
        s.total_yards,
        s.side_dispersion,
        s.spin_axis_deg,
        s.launch_direction_deg
    from shots as s
    inner join sessions as sess
        on s.source = sess.source
    left join {{ ref('dim_player') }} as dp
        on
            s.player = dp.player
            and sess.session_date between dp.valid_from and dp.valid_to
    left join {{ ref('dim_club') }} as dc
        on
            s.player = dc.player
            and s.club = dc.club_type
            and sess.session_date between dc.valid_from and dc.valid_to
)

select
    *,
    case
        when club_model_year is not null
            then extract(year from session_date) - club_model_year
    end as club_age_years
from joined

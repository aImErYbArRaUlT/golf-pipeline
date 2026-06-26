-- dim_player - SCD Type 2.
-- A player's attributes change over time (handicap most of all), so each
-- profile period is its own row with a validity window. A shot attributes to
-- the player version that was current at its session date. Validity is derived
-- from effective_from: a version is valid until the day before the next one.
with profiles as (
    select
        player,
        handicap_band,
        age_band,
        gender,
        cast(effective_from as date) as valid_from
    from {{ ref('player_profiles') }}
),

versioned as (
    select
        *,
        coalesce(
            date_sub(
                lead(valid_from) over (partition by player order by valid_from),
                interval 1 day
            ),
            date '9999-12-31'
        ) as valid_to
    from profiles
)

select
    to_hex(md5(concat(player, '|', cast(valid_from as string)))) as player_key,
    player,
    handicap_band,
    age_band,
    gender,
    valid_from,
    valid_to,
    valid_to = date '9999-12-31' as is_current
from versioned

-- dim_club - SCD Type 2 + enriched.
-- Built from player-reported clubs joined to the club-spec reference for stock
-- specs. Custom clubs (bent loft, aftermarket shaft) fall back to the player's
-- reported specs instead of the reference. Each (player, club) configuration
-- period is its own validity window, so a shot attributes to the club setup as
-- it was at the session date.
with player_clubs as (
    select
        player,
        club_type,
        make,
        model,
        safe_cast(year as int64) as model_year,
        lower(is_custom) = 'true' as is_custom,
        reported_loft_deg,
        reported_length_in,
        nullif(reported_shaft, '') as reported_shaft,
        cast(effective_from as date) as valid_from
    from {{ ref('player_clubs') }}
),

specs as (
    select
        make,
        model,
        safe_cast(year as int64) as model_year,
        club_type,
        stock_loft_deg,
        standard_length_in,
        stock_shaft
    from {{ ref('club_specs') }}
),

enriched as (
    select
        pc.player,
        pc.club_type,
        pc.make,
        pc.model,
        pc.model_year,
        pc.is_custom,
        pc.valid_from,
        -- custom -> reported specs; stock -> reference specs
        if(pc.is_custom, pc.reported_loft_deg, s.stock_loft_deg) as loft_deg,
        if(pc.is_custom, pc.reported_length_in, s.standard_length_in) as length_in,
        if(pc.is_custom, pc.reported_shaft, s.stock_shaft) as shaft
    from player_clubs as pc
    left join specs as s
        on
            pc.make = s.make
            and pc.model = s.model
            and pc.model_year = s.model_year
            and pc.club_type = s.club_type
),

versioned as (
    select
        *,
        coalesce(
            date_sub(
                lead(valid_from) over (partition by player, club_type order by valid_from),
                interval 1 day
            ),
            date '9999-12-31'
        ) as valid_to
    from enriched
)

select
    to_hex(md5(concat(player, '|', club_type, '|', cast(valid_from as string)))) as club_key,
    player,
    club_type,
    make,
    model,
    model_year,
    is_custom,
    loft_deg,
    length_in,
    shaft,
    valid_from,
    valid_to,
    valid_to = date '9999-12-31' as is_current
from versioned

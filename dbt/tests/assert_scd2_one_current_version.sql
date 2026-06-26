-- SCD2 invariant: each entity has exactly one current version.
-- Returns any player / (player, club) with != 1 is_current row (a failure).
with player_currents as (
    select
        player,
        countif(is_current) as n_current
    from {{ ref('dim_player') }}
    group by player
),

club_currents as (
    select
        concat(player, ' / ', club_type) as entity,
        countif(is_current) as n_current
    from {{ ref('dim_club') }}
    group by player, club_type
)

select
    player as entity,
    n_current
from player_currents
where n_current != 1
union all
select
    entity,
    n_current
from club_currents
where n_current != 1

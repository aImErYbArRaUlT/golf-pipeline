-- SCD2 invariant: an entity's version windows must not overlap.
-- For each entity ordered by valid_from, the previous version's valid_to must
-- be strictly before the next version's valid_from. Any violation is returned.
with player_windows as (
    select
        player as entity,
        valid_from,
        valid_to,
        lag(valid_to) over (partition by player order by valid_from) as prev_valid_to
    from {{ ref('dim_player') }}
),

club_windows as (
    select
        concat(player, ' / ', club_type) as entity,
        valid_from,
        valid_to,
        lag(valid_to) over (partition by player, club_type order by valid_from) as prev_valid_to
    from {{ ref('dim_club') }}
)

select
    entity,
    valid_from,
    prev_valid_to
from player_windows
where prev_valid_to >= valid_from
union all
select
    entity,
    valid_from,
    prev_valid_to
from club_windows
where prev_valid_to >= valid_from

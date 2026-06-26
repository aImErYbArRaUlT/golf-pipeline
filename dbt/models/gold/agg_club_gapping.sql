-- Club gapping mart: the analysis golfers actually want - what each club does,
-- and the distance gaps between them. Aggregates fct_shots up to one row per
-- (source, player, club), joining the dims for their names.
--
-- Design choices that matter for honest numbers:
--   * median carry leads, not mean - range data is full of mishits that drag
--     the average around; the median is robust to them.
--   * p10/p90 give a realistic spread band; carry_sd quantifies consistency.
--   * gap_to_shorter_club is the literal "gapping" - the median-carry step down
--     to the next club, so a player can see overlaps or holes in their set.
--   * shot_count is kept visible: a 12-shot range sample is suggestive, not
--     gospel. (Phase 3.5 sharpens this: mishit filtering, measured-vs-estimated
--     separation, and handicap/loft context.)

with shots as (
    select
        f.source,
        f.carry_method,
        pl.player,
        c.club_type as club,
        f.carry_yards,
        f.total_yards,
        f.side_dispersion
    from {{ ref('fct_shots') }} as f
    inner join {{ ref('dim_club') }} as c on f.club_key = c.club_key
    inner join {{ ref('dim_player') }} as pl on f.player_key = pl.player_key
    where f.carry_yards is not null
),

aggregated as (
    select
        source,
        carry_method,
        player,
        club,
        count(*) as shot_count,
        round(avg(carry_yards), 1) as avg_carry_yards,
        round(approx_quantiles(carry_yards, 2)[offset(1)], 1) as median_carry_yards,
        round(approx_quantiles(carry_yards, 10)[offset(1)], 1) as carry_p10_yards,
        round(approx_quantiles(carry_yards, 10)[offset(9)], 1) as carry_p90_yards,
        round(stddev(carry_yards), 1) as carry_consistency_sd,
        round(avg(total_yards), 1) as avg_total_yards,
        -- magnitude of the typical miss, and the signed bias (+right / -left)
        round(avg(abs(side_dispersion)), 1) as avg_offline_yards,
        round(avg(side_dispersion), 1) as avg_side_bias_yards
    from shots
    group by source, carry_method, player, club
)

select
    to_hex(md5(concat(source, '|', player, '|', club))) as gapping_key,
    aggregated.*,
    -- the gap (in median carry) down to the player's next-shorter club
    round(
        median_carry_yards - lead(median_carry_yards) over (
            partition by source, player order by median_carry_yards desc
        ),
        1
    ) as gap_to_shorter_club_yards
from aggregated

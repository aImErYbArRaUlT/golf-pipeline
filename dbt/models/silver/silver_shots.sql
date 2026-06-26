-- Conformed, cleaned shots across all sources.
-- Each source has its own stg_ model emitting the common schema; silver is
-- their union. Adding a source = adding one `union all` here (Phase 3).
-- Light cleaning: drop rows whose core metric failed to parse.

with conformed as (
    select * from {{ ref('stg_trackman') }}
    union all
    select * from {{ ref('stg_foresight') }}
    union all
    select * from {{ ref('stg_caddieset') }}
    union all
    select * from {{ ref('stg_flightscope') }}
    union all
    select * from {{ ref('stg_manual') }}
)

select *
from conformed
where ball_speed_mph is not null

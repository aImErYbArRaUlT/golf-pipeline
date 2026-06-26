-- dim_session.
-- One row per logical session - in this build, one ingested source = one
-- session (real multi-session ingestion would key this by an upload/session id).
-- carry_method flags whether carry was measured (radar/camera) or estimated
-- (consumer monitor), so indoor estimates aren't silently compared with outdoor
-- measurements.
select
    to_hex(md5(session_id)) as session_key,
    session_id,
    source,
    cast(session_date as date) as session_date,
    indoor_outdoor,
    device,
    carry_method,
    ball_type
from {{ ref('session_manifest') }}

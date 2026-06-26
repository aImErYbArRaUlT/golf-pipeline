"""PySpark silver transform - the conforming/cleaning/dedup done distributed.

This re-expresses the dbt silver layer as a PySpark job to demonstrate the
distributed pattern: read the per-source bronze Parquet from object storage
(MinIO over s3a), conform each source into the common schema, dedup, validate,
and write one unified silver Parquet back. At this data size Spark is overkill
mechanically - but the job is written to scale (DataFrame API, a Window for the
keep-latest dedup, lazy evaluation, narrow per-source transforms before the
union) and reads/writes from object storage exactly as a cluster job would.

Idempotent: silver is overwritten each run.

Run via `just spark-silver` (spark-submit in the spark container).
"""

from __future__ import annotations

import os

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

MS_TO_MPH = 2.2369362920544
M_TO_YARDS = 1.0936132983377

# Exact common-schema column order (matches the dbt models).
COMMON_SCHEMA = [
    "shot_id",
    "source",
    "player",
    "club",
    "session_date",
    "ball_speed_mph",
    "club_speed_mph",
    "smash_factor",
    "launch_angle_deg",
    "spin_rate_rpm",
    "carry_yards",
    "total_yards",
    "side_dispersion",
    "spin_axis_deg",
    "launch_direction_deg",
]


def _shot_id() -> Column:
    """Stable surrogate key: md5(source + row index) - same as the dbt models."""
    return F.md5(F.concat(F.col("_source"), F.lit("-"), F.col("_row_index").cast("string")))


def _num(col: str) -> Column:
    """Cast a raw string column to double, scrubbing NaN to null (like safe_cast)."""
    c = F.col(col).cast("double")
    return F.when(F.isnan(c), None).otherwise(c)


def conform_trackman(df: DataFrame) -> DataFrame:
    """TrackMan: already imperial; clean the spin sentinel; default player/date."""
    spin = _num("spin_rate")
    return df.select(
        _shot_id().alias("shot_id"),
        F.col("_source").alias("source"),
        F.lit("unknown").alias("player"),
        F.col("club").alias("club"),
        F.lit(None).cast("date").alias("session_date"),
        _num("ball_speed").alias("ball_speed_mph"),
        _num("club_speed").alias("club_speed_mph"),
        _num("smash_factor").alias("smash_factor"),
        _num("launch_angle").alias("launch_angle_deg"),
        F.when(spin < 0, None).otherwise(spin).alias("spin_rate_rpm"),
        _num("carry_flat_length").alias("carry_yards"),
        _num("total").alias("total_yards"),
        _num("side_total").alias("side_dispersion"),
        _num("spin_axis").alias("spin_axis_deg"),
        _num("launch_direction").alias("launch_direction_deg"),
    )


def conform_foresight(df: DataFrame) -> DataFrame:
    """Foresight/Garmin: imperial; parse the M/d/yy timestamp into a date."""
    return df.select(
        _shot_id().alias("shot_id"),
        F.col("_source").alias("source"),
        F.when(F.col("player") == "", None).otherwise(F.col("player")).alias("player"),
        F.col("club_type").alias("club"),
        # Garmin sessions use 24-hour and 12-hour (AM/PM) timestamps; try both.
        F.to_date(
            F.coalesce(
                F.to_timestamp(F.col("date"), "M/d/yy H:mm:ss"),
                F.to_timestamp(F.col("date"), "MM/dd/yy hh:mm:ss a"),
            )
        ).alias("session_date"),
        _num("ball_speed").alias("ball_speed_mph"),
        _num("club_speed").alias("club_speed_mph"),
        _num("smash_factor").alias("smash_factor"),
        _num("launch_angle").alias("launch_angle_deg"),
        _num("spin_rate").alias("spin_rate_rpm"),
        _num("carry_distance").alias("carry_yards"),
        _num("total_distance").alias("total_yards"),
        _num("total_deviation_distance").alias("side_dispersion"),
        _num("spin_axis").alias("spin_axis_deg"),
        _num("launch_direction").alias("launch_direction_deg"),
    )


_CLUB_CODES = {
    "W1": "Driver",
    "W3": "3 Wood",
    "I4": "4 Iron",
    "I5": "5 Iron",
    "I6": "6 Iron",
    "I7": "7 Iron",
    "I8": "8 Iron",
    "I9": "9 Iron",
}


def conform_caddieset(df: DataFrame) -> DataFrame:
    """CaddieSet: metric -> imperial, dedup the two camera views, derive spin."""
    # One physical shot is recorded once per camera view; keep one. Order by the
    # row index so the kept row (and its shot_id) is deterministic.
    fingerprint = F.concat_ws(
        "|",
        "golferid",
        "clubtype",
        "carry",
        "distance",
        "ballspeed",
        "spinback",
        "spinside",
        "lrdistanceout",
    )
    deduped = (
        df.withColumn("_fp", fingerprint)
        .withColumn(
            "_rank",
            F.row_number().over(Window.partitionBy("_fp").orderBy(F.col("_row_index").cast("int"))),
        )
        .where(F.col("_rank") == 1)
    )

    club = F.col("clubtype")
    for code, name in _CLUB_CODES.items():
        club = F.when(F.col("clubtype") == code, name).otherwise(club)

    back, side = _num("spinback"), _num("spinside")
    return deduped.select(
        _shot_id().alias("shot_id"),
        F.col("_source").alias("source"),
        F.concat(F.lit("Golfer "), F.col("golferid")).alias("player"),
        club.alias("club"),
        F.lit(None).cast("date").alias("session_date"),
        (_num("ballspeed") * MS_TO_MPH).alias("ball_speed_mph"),
        F.lit(None).cast("double").alias("club_speed_mph"),
        F.lit(None).cast("double").alias("smash_factor"),
        F.lit(None).cast("double").alias("launch_angle_deg"),
        F.sqrt(F.pow(back, 2) + F.pow(side, 2)).alias("spin_rate_rpm"),
        (_num("carry") * M_TO_YARDS).alias("carry_yards"),
        (_num("distance") * M_TO_YARDS).alias("total_yards"),
        (_num("lrdistanceout") * M_TO_YARDS).alias("side_dispersion"),
        _num("spinaxis").alias("spin_axis_deg"),
        _num("directionangle").alias("launch_direction_deg"),
    )


def conform_flightscope(df: DataFrame) -> DataFrame:
    """FlightScope Mevo: imperial; date from the file path; normalise club codes."""
    code = F.col("club")
    club = (
        F.when(code == "Driver", "Driver")
        .when(code == "PW", "Pitching Wedge")
        .when(code == "GW", "Gap Wedge")
        .when(code == "SW", "Sand Wedge")
        .when(code == "LW", "Lob Wedge")
        .when(
            code.rlike(r"^[0-9]+I$"),
            F.concat(F.regexp_extract(code, r"^([0-9]+)I$", 1), F.lit(" Iron")),
        )
        .when(
            code.rlike(r"^[0-9]+W$"),
            F.concat(F.regexp_extract(code, r"^([0-9]+)W$", 1), F.lit(" Wood")),
        )
        .otherwise(code)
    )
    return df.select(
        _shot_id().alias("shot_id"),
        F.col("_source").alias("source"),
        F.lit("unknown").alias("player"),
        club.alias("club"),
        F.to_date(F.regexp_extract(F.col("_source_file"), r"(\d{4}-\d{2}-\d{2})", 1)).alias(
            "session_date"
        ),
        _num("ball_speed_mph").alias("ball_speed_mph"),
        _num("club_speed_mph").alias("club_speed_mph"),
        _num("smash").alias("smash_factor"),
        _num("launch_angle_v").alias("launch_angle_deg"),
        _num("spin_rpm").alias("spin_rate_rpm"),
        _num("carry_distance_yds").alias("carry_yards"),
        F.lit(None).cast("double").alias("total_yards"),
        F.lit(None).cast("double").alias("side_dispersion"),
        F.lit(None).cast("double").alias("spin_axis_deg"),
        F.lit(None).cast("double").alias("launch_direction_deg"),
    )


def build_spark() -> SparkSession:
    """SparkSession wired to MinIO via the s3a connector."""
    endpoint = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")
    return (
        SparkSession.builder.appName("golf-silver-transform")
        # Lenient datetime parsing: return null on a format mismatch (so the
        # coalesce of two Garmin timestamp formats works) instead of throwing,
        # matching BigQuery's safe.parse_timestamp behaviour.
        .config("spark.sql.legacy.timeParserPolicy", "LEGACY")
        .config("spark.hadoop.fs.s3a.endpoint", endpoint)
        .config("spark.hadoop.fs.s3a.access.key", os.environ["MINIO_ROOT_USER"])
        .config("spark.hadoop.fs.s3a.secret.key", os.environ["MINIO_ROOT_PASSWORD"])
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
        .getOrCreate()
    )


def main() -> None:
    bronze_bucket = os.environ.get("MINIO_BUCKET_BRONZE", "bronze")
    silver_bucket = os.environ.get("MINIO_BUCKET_SILVER", "silver")
    spark = build_spark()
    spark.sparkContext.setLogLevel("WARN")

    def bronze(src: str) -> DataFrame:
        return spark.read.parquet(f"s3a://{bronze_bucket}/parquet/{src}/{src}.parquet")

    conformers = {
        "trackman": conform_trackman,
        "foresight": conform_foresight,
        "caddieset": conform_caddieset,
        "flightscope": conform_flightscope,
    }

    parts = [fn(bronze(src)).select(*COMMON_SCHEMA) for src, fn in conformers.items()]
    silver = parts[0]
    for p in parts[1:]:
        silver = silver.unionByName(p)

    # Validation: a shot needs a ball speed to be usable downstream.
    silver = silver.where(F.col("ball_speed_mph").isNotNull())
    silver.cache()

    total = silver.count()
    print("=== silver row counts by source ===")
    silver.groupBy("source").count().orderBy("source").show(truncate=False)
    print(f"=== total silver rows: {total} ===")

    out = f"s3a://{silver_bucket}/silver_shots"
    silver.write.mode("overwrite").parquet(out)
    print(f"=== wrote silver -> {out} ===")
    spark.stop()


if __name__ == "__main__":
    main()

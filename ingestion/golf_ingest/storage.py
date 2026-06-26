"""MinIO object storage (S3-compatible).

MinIO speaks the S3 API, so we use boto3 - the exact same client code would
work against real S3 by changing only the endpoint and credentials. That's
the point of using MinIO locally: parity with cloud object storage.
"""

from __future__ import annotations

import boto3
from botocore.client import Config

from .config import MinioConfig


def make_client(cfg: MinioConfig):
    """Build an S3 client pointed at MinIO."""
    return boto3.client(
        "s3",
        endpoint_url=cfg.endpoint,
        aws_access_key_id=cfg.access_key,
        aws_secret_access_key=cfg.secret_key,
        config=Config(signature_version="s3v4"),
    )


def put_object(cfg: MinioConfig, key: str, data: bytes) -> str:
    """Upload bytes to the bronze bucket under `key`. Returns the s3:// URI.

    Idempotent: re-uploading the same key overwrites in place (no dupes).
    """
    client = make_client(cfg)
    client.put_object(Bucket=cfg.bucket_bronze, Key=key, Body=data)
    return f"s3://{cfg.bucket_bronze}/{key}"

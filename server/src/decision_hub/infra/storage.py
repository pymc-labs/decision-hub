"""S3 storage operations for skill zip files and search logs.

Provides functions for uploading skill packages, generating presigned download
URLs, computing file checksums, and storing search query logs. All functions
are pure (aside from S3 I/O) and take an explicit S3 client rather than
relying on global state.
"""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import boto3
from botocore.client import BaseClient
from loguru import logger


def create_s3_client(region: str, access_key_id: str, secret_access_key: str) -> BaseClient:
    """Create an S3 client with explicit credentials.

    Args:
        region: AWS region name (e.g. 'us-east-1').
        access_key_id: AWS access key ID.
        secret_access_key: AWS secret access key.

    Returns:
        A configured boto3 S3 client.
    """
    return boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )


def upload_skill_zip(client: BaseClient, bucket: str, s3_key: str, data: bytes) -> None:
    """Upload a skill zip file to S3.

    Args:
        client: Configured S3 client.
        bucket: Target S3 bucket name.
        s3_key: Object key within the bucket (e.g. 'skills/org/name/1.0.0.zip').
        data: Raw bytes of the zip file to upload.
    """
    logger.info("Uploading skill zip to s3://{}/{} ({} bytes)", bucket, s3_key, len(data))
    client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=data,
        ContentType="application/zip",
    )


def delete_skill_zip(client: BaseClient, bucket: str, s3_key: str) -> None:
    """Delete a skill zip file from S3.

    Args:
        client: Configured S3 client.
        bucket: S3 bucket name containing the object.
        s3_key: Object key to delete.
    """
    logger.info("Deleting s3://{}/{}", bucket, s3_key)
    client.delete_object(Bucket=bucket, Key=s3_key)


def generate_presigned_url(
    client: BaseClient,
    bucket: str,
    s3_key: str,
    expiration: int = 3600,
) -> str:
    """Generate a presigned URL for downloading a skill zip from S3.

    Args:
        client: Configured S3 client.
        bucket: S3 bucket name containing the object.
        s3_key: Object key to generate the URL for.
        expiration: URL lifetime in seconds (default: 1 hour).

    Returns:
        A presigned HTTPS URL string that grants temporary read access.
    """
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": s3_key},
        ExpiresIn=expiration,
    )


def download_skill_zip(client: BaseClient, bucket: str, s3_key: str) -> bytes:
    """Download a skill zip file from S3.

    Args:
        client: Configured S3 client.
        bucket: S3 bucket name containing the object.
        s3_key: Object key to download.

    Returns:
        Raw bytes of the zip file.
    """
    resp = client.get_object(Bucket=bucket, Key=s3_key)
    return resp["Body"].read()


def compute_checksum(data: bytes) -> str:
    """Compute SHA256 hex digest of data.

    Args:
        data: Raw bytes to hash.

    Returns:
        Lowercase hex string of the SHA256 digest.
    """
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Eval log chunk operations
# ---------------------------------------------------------------------------


def upload_eval_log_chunk(
    client: BaseClient,
    bucket: str,
    s3_prefix: str,
    seq: int,
    events_jsonl: str,
) -> str:
    """Upload a JSONL chunk of eval log events to S3.

    Args:
        client: Configured S3 client.
        bucket: Target S3 bucket name.
        s3_prefix: S3 prefix (e.g. 'eval-logs/{run_id}/').
        seq: Chunk sequence number (zero-padded to 4 digits in the key).
        events_jsonl: Newline-delimited JSON string of events.

    Returns:
        The S3 key of the uploaded chunk.
    """
    s3_key = f"{s3_prefix}{seq:04d}.jsonl"
    client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=events_jsonl.encode("utf-8"),
        ContentType="application/x-ndjson",
    )
    return s3_key


def list_eval_log_chunks(
    client: BaseClient,
    bucket: str,
    s3_prefix: str,
    after_seq: int = 0,
) -> list[tuple[int, str]]:
    """List eval log chunk keys with sequence number > after_seq.

    Returns:
        List of (seq, s3_key) tuples sorted by seq ascending.
    """
    resp = client.list_objects_v2(Bucket=bucket, Prefix=s3_prefix)
    contents = resp.get("Contents", [])

    chunks: list[tuple[int, str]] = []
    for obj in contents:
        key = obj["Key"]
        # Extract seq from filename like 'eval-logs/{run_id}/0001.jsonl'
        filename = key.rsplit("/", 1)[-1]
        if not filename.endswith(".jsonl"):
            continue
        seq_str = filename.replace(".jsonl", "")
        try:
            seq = int(seq_str)
        except ValueError:
            continue
        if seq > after_seq:
            chunks.append((seq, key))

    chunks.sort(key=lambda x: x[0])
    return chunks


def read_eval_log_chunk(
    client: BaseClient,
    bucket: str,
    s3_key: str,
) -> str:
    """Read and return the content of an eval log chunk from S3."""
    resp = client.get_object(Bucket=bucket, Key=s3_key)
    return resp["Body"].read().decode("utf-8")


def delete_eval_logs(
    client: BaseClient,
    bucket: str,
    s3_prefix: str,
) -> int:
    """Delete all eval log chunks under a prefix.

    Returns:
        Number of objects deleted.
    """
    resp = client.list_objects_v2(Bucket=bucket, Prefix=s3_prefix)
    contents = resp.get("Contents", [])
    if not contents:
        return 0

    objects = [{"Key": obj["Key"]} for obj in contents]
    client.delete_objects(
        Bucket=bucket,
        Delete={"Objects": objects},
    )
    return len(objects)


# ---------------------------------------------------------------------------
# Search log operations
# ---------------------------------------------------------------------------


def upload_search_log(
    client: BaseClient,
    bucket: str,
    log_id: UUID,
    query: str,
    response: str,
    metadata: dict,
) -> str:
    """Upload a search log entry to S3 as JSON.

    Args:
        client: Configured S3 client.
        bucket: Target S3 bucket name.
        log_id: UUID of the search log entry.
        query: The full search query string.
        response: The full LLM response text.
        metadata: Additional metadata (results_count, model, latency_ms, user_id, etc.).

    Returns:
        The S3 key of the uploaded log.
    """
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    s3_key = f"search-logs/{date_str}/{log_id}.json"

    log_data = {
        "id": str(log_id),
        "query": query,
        "response": response,
        "metadata": metadata,
    }

    client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=json.dumps(log_data, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    logger.debug("Uploaded search log to s3://{}/{}", bucket, s3_key)
    return s3_key

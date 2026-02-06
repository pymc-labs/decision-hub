"""S3 storage operations for skill zip files.

Provides functions for uploading skill packages, generating presigned download
URLs, and computing file checksums. All functions are pure (aside from S3 I/O)
and take an explicit S3 client rather than relying on global state.
"""

import hashlib

import boto3
from botocore.client import BaseClient


def create_s3_client(
    region: str, access_key_id: str, secret_access_key: str
) -> BaseClient:
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


def upload_skill_zip(
    client: BaseClient, bucket: str, s3_key: str, data: bytes
) -> None:
    """Upload a skill zip file to S3.

    Args:
        client: Configured S3 client.
        bucket: Target S3 bucket name.
        s3_key: Object key within the bucket (e.g. 'skills/org/name/1.0.0.zip').
        data: Raw bytes of the zip file to upload.
    """
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


def compute_checksum(data: bytes) -> str:
    """Compute SHA256 hex digest of data.

    Args:
        data: Raw bytes to hash.

    Returns:
        Lowercase hex string of the SHA256 digest.
    """
    return hashlib.sha256(data).hexdigest()

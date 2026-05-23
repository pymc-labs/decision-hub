"""Tests for the create_s3_client factory in infra/storage.py.

Covers the timeout / retry hardening that prevents a dead S3 endpoint
from hanging worker processes indefinitely.
"""

from decision_hub.infra.storage import create_s3_client


def _build() -> object:
    return create_s3_client(
        region="us-east-1",
        access_key_id="AKIA-test",
        secret_access_key="secret-test",
    )


def test_client_has_bounded_connect_timeout() -> None:
    client = _build()
    cfg = client.meta.config
    assert cfg.connect_timeout is not None
    assert cfg.connect_timeout <= 30, "connect_timeout must be bounded so a dead endpoint fails fast"


def test_client_has_bounded_read_timeout() -> None:
    client = _build()
    cfg = client.meta.config
    assert cfg.read_timeout is not None
    assert cfg.read_timeout <= 120, "read_timeout must be bounded to avoid hanging reads"


def test_client_uses_standard_retry_mode() -> None:
    client = _build()
    retries = client.meta.config.retries or {}
    assert retries.get("mode") == "standard"
    assert (retries.get("max_attempts") or retries.get("total_max_attempts", 0)) >= 2


def test_endpoint_url_passed_through_for_minio() -> None:
    client = create_s3_client(
        region="us-east-1",
        access_key_id="x",
        secret_access_key="y",
        endpoint_url="http://localhost:9000",
    )
    assert client.meta.endpoint_url == "http://localhost:9000"

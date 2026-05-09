"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter


def _make_request(host: str = "127.0.0.1", *, forwarded: str | None = None, trusted_proxy_count: int = 0) -> MagicMock:
    """Create a mock Request with a given client IP and optional proxy chain.

    ``trusted_proxy_count`` is the value the limiter would read from
    ``request.app.state.settings.trusted_proxy_count``.  The default ``0``
    preserves the historical "read request.client.host" behaviour, so the
    tests written before proxy support was added continue to pass.
    """
    request = MagicMock()
    request.client.host = host
    request.headers = {"x-forwarded-for": forwarded} if forwarded is not None else {}
    request.app.state.settings.trusted_proxy_count = trusted_proxy_count
    return request


class TestRateLimiter:
    """Unit tests for the RateLimiter class."""

    def test_allows_requests_under_limit(self) -> None:
        """Requests within the limit should pass without error."""
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        request = _make_request()

        for _ in range(3):
            limiter(request)  # should not raise

    def test_blocks_requests_over_limit(self) -> None:
        """The request exceeding the limit should raise HTTP 429."""
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        request = _make_request()

        for _ in range(3):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429

    def test_different_ips_have_separate_limits(self) -> None:
        """Each IP has its own counter."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        req_a = _make_request("10.0.0.1")
        req_b = _make_request("10.0.0.2")

        # Fill up IP A's limit
        for _ in range(2):
            limiter(req_a)

        # IP A should be blocked
        with pytest.raises(HTTPException):
            limiter(req_a)

        # IP B should still be allowed
        limiter(req_b)  # should not raise

    def test_window_expiry_resets_limit(self) -> None:
        """After the window expires, requests are allowed again."""
        limiter = RateLimiter(max_requests=2, window_seconds=1)
        request = _make_request()

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            for _ in range(2):
                limiter(request)

            with pytest.raises(HTTPException):
                limiter(request)

            # Advance past the 1-second window
            mock_time.monotonic.return_value = 1001.5
            limiter(request)  # should not raise

    def test_no_client_uses_unknown_key(self) -> None:
        """Requests with client=None use 'unknown' as the rate limit key."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        request = MagicMock()
        request.client = None
        request.headers = {}
        request.app.state.settings.trusted_proxy_count = 0

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429


class TestRateLimiterBehindProxy:
    """Pin the proxy-aware behaviour added to fix the per-IP collapse bug.

    Without this support, every request behind Modal/Cloudflare/ALB shares
    the proxy's IP as the rate-limit key, so a single noisy client can
    exhaust the bucket for everyone — or, conversely, the bucket never
    triggers because traffic is averaged across all real clients.
    """

    def test_with_trusted_proxy_distinct_clients_have_separate_buckets(self) -> None:
        """Two clients behind one trusted proxy must not share a bucket."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        # Both arrive via the same proxy IP; only X-Forwarded-For differs.
        req_a = _make_request(host="10.0.0.1", forwarded="203.0.113.5, 10.0.0.1", trusted_proxy_count=1)
        req_b = _make_request(host="10.0.0.1", forwarded="203.0.113.7, 10.0.0.1", trusted_proxy_count=1)

        for _ in range(2):
            limiter(req_a)

        with pytest.raises(HTTPException):
            limiter(req_a)

        # Client B remains unaffected — exactly the bug we are fixing.
        limiter(req_b)
        limiter(req_b)
        with pytest.raises(HTTPException):
            limiter(req_b)

    def test_with_no_proxy_setting_forwarded_header_is_ignored(self) -> None:
        """``trusted_proxy_count=0`` (the default) must not trust the header.

        Otherwise any client could spoof ``X-Forwarded-For`` to defeat the
        rate limiter.  This test pins the safe default explicitly.
        """
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        req_a = _make_request(host="10.0.0.1", forwarded="203.0.113.5", trusted_proxy_count=0)
        req_b = _make_request(host="10.0.0.1", forwarded="203.0.113.7", trusted_proxy_count=0)
        # Both share the bucket because ``request.client.host`` is identical
        # and the X-Forwarded-For header is intentionally ignored.
        limiter(req_a)
        limiter(req_b)
        with pytest.raises(HTTPException):
            limiter(req_a)

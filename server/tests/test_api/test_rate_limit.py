"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter


def _make_request(host: str = "127.0.0.1", headers: dict[str, str] | None = None) -> MagicMock:
    """Create a mock Request with a given client IP and optional headers."""
    request = MagicMock()
    request.client.host = host
    # Simulate Starlette's case-insensitive Headers.get — always .lower() the key.
    header_map = {k.lower(): v for k, v in (headers or {}).items()}
    request.headers = MagicMock()
    request.headers.get = lambda key, default=None: header_map.get(key.lower(), default)
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
        # Empty headers — force the fallback path in _client_ip.
        request.headers = MagicMock()
        request.headers.get = lambda key, default=None: default

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429

    def test_uses_x_forwarded_for_leftmost(self) -> None:
        """Behind a reverse proxy, the real client IP comes from X-Forwarded-For.

        Regression: without this, ``request.client.host`` is the proxy's
        IP (all clients share one bucket) and a single malicious client
        can lock the whole world out of an endpoint.
        """
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        # Two different real clients coming through the same proxy.
        req_a = _make_request(host="10.0.0.99", headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.99"})
        req_b = _make_request(host="10.0.0.99", headers={"X-Forwarded-For": "2.2.2.2, 10.0.0.99"})

        limiter(req_a)  # 1.1.1.1 spends its quota
        # 2.2.2.2 must still have its own bucket.
        limiter(req_b)  # should NOT raise

        with pytest.raises(HTTPException):
            limiter(req_a)  # 1.1.1.1 is now blocked

    def test_x_real_ip_fallback(self) -> None:
        """When only X-Real-IP is present (no XFF), use it."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        req = _make_request(host="10.0.0.99", headers={"X-Real-IP": "3.3.3.3"})
        limiter(req)
        with pytest.raises(HTTPException):
            limiter(req)

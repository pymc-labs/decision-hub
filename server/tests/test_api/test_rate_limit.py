"""Tests for decision_hub.api.rate_limit -- sliding-window rate limiter."""

import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter


def _make_request(host: str = "127.0.0.1") -> MagicMock:
    """Create a minimal mock Request with a client IP."""
    request = MagicMock()
    request.client.host = host
    return request


class TestRateLimiter:
    """Unit tests for the RateLimiter class."""

    def test_allows_requests_under_limit(self) -> None:
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        request = _make_request()

        # Should not raise for first 3 requests
        for _ in range(3):
            limiter(request)

    def test_blocks_requests_over_limit(self) -> None:
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        request = _make_request()

        for _ in range(3):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429
        assert "Rate limit exceeded" in exc_info.value.detail

    def test_different_ips_have_separate_limits(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=60)

        req_a = _make_request("10.0.0.1")
        req_b = _make_request("10.0.0.2")

        # Fill up IP A's limit
        limiter(req_a)
        limiter(req_a)

        # IP B should still be allowed
        limiter(req_b)

        # IP A should be blocked
        with pytest.raises(HTTPException) as exc_info:
            limiter(req_a)
        assert exc_info.value.status_code == 429

    def test_window_expiry_resets_limit(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=1)
        request = _make_request()

        limiter(request)
        limiter(request)

        # Should be blocked now
        with pytest.raises(HTTPException):
            limiter(request)

        # Wait for window to expire
        time.sleep(1.1)

        # Should be allowed again
        limiter(request)

    def test_no_client_uses_unknown_key(self) -> None:
        """Requests without client info should still be rate-limited."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        request = MagicMock()
        request.client = None

        limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429

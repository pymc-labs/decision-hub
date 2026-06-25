"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter


def _make_request(host: str = "127.0.0.1") -> MagicMock:
    """Create a mock Request with a given client IP."""
    request = MagicMock()
    request.client.host = host
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

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429

    def test_purge_stale_drops_expired_ips(self) -> None:
        """Stale IPs are evicted from the internal dict every _PURGE_EVERY
        calls, bounding memory growth.

        Regression test for a bug where the purge used a modulo over the
        live count (``total % 100 == 0``), which almost never fired, so the
        dict grew unbounded over the container's lifetime.
        """
        # Tight knob: purge every 5 calls instead of 100.
        limiter = RateLimiter(max_requests=10, window_seconds=1)
        limiter._PURGE_EVERY = 5  # type: ignore[misc]

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            # Five distinct stale IPs at t=1000.
            mock_time.monotonic.return_value = 1000.0
            for i in range(5):
                limiter(_make_request(f"10.0.0.{i}"))
            assert len(limiter._requests) == 5

            # Advance well past the window so all five are stale.
            mock_time.monotonic.return_value = 1100.0
            # Five more calls from a fresh IP — the 5th call should purge
            # the stale entries (calls_since_purge wraps).
            for _ in range(5):
                limiter(_make_request("10.0.0.99"))

            # Only the active IP should remain.
            assert list(limiter._requests.keys()) == ["10.0.0.99"]

    def test_purge_counter_advances_every_call(self) -> None:
        """Each call increments the purge counter exactly once, regardless
        of how many timestamps already exist for the caller's IP."""
        limiter = RateLimiter(max_requests=100, window_seconds=60)
        request = _make_request()

        for n in range(1, 11):
            limiter(request)
            assert limiter._calls_since_purge == n % limiter._PURGE_EVERY

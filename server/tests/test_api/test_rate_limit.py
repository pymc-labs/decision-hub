"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter


def _make_request(host: str = "127.0.0.1", headers: dict[str, str] | None = None) -> MagicMock:
    """Create a mock Request with a given client IP and optional headers."""
    request = MagicMock()
    request.client.host = host
    request.headers = headers or {}
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

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429

    def test_x_forwarded_for_takes_precedence_over_peer(self) -> None:
        """The proxy's peer IP must NOT be the limiter key when XFF is present.

        Modal (and most reverse proxies) put the real client in
        X-Forwarded-For. Falling back to request.client.host would collapse
        every user into one bucket per container.
        """
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        # Two requests from client-A behind the proxy
        req_a = _make_request(host="10.0.0.100", headers={"x-forwarded-for": "203.0.113.1"})
        for _ in range(2):
            limiter(req_a)
        with pytest.raises(HTTPException):
            limiter(req_a)

        # Client-B (different XFF) is behind the SAME proxy peer — must not
        # be blocked by A's usage.
        req_b = _make_request(host="10.0.0.100", headers={"x-forwarded-for": "203.0.113.2"})
        limiter(req_b)  # should not raise

    def test_x_forwarded_for_uses_leftmost_hop(self) -> None:
        """Multi-hop XFF (client, proxy1, proxy2) — leftmost is the client."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        req = _make_request(
            host="10.0.0.1",
            headers={"x-forwarded-for": "203.0.113.5, 10.0.0.2, 10.0.0.1"},
        )
        limiter(req)
        req_same = _make_request(
            host="10.0.0.9",
            headers={"x-forwarded-for": "203.0.113.5, other, hops"},
        )
        with pytest.raises(HTTPException):
            limiter(req_same)

    def test_x_real_ip_fallback(self) -> None:
        """Falls back to X-Real-IP when X-Forwarded-For is absent."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        req_a = _make_request(host="10.0.0.100", headers={"x-real-ip": "198.51.100.1"})
        req_b = _make_request(host="10.0.0.100", headers={"x-real-ip": "198.51.100.2"})
        limiter(req_a)
        limiter(req_b)  # different real IP → not throttled
        with pytest.raises(HTTPException):
            limiter(req_a)

    def test_periodic_purge_runs_at_wall_clock_cadence(self) -> None:
        """Stale IPs are purged when the purge interval elapses, not by modulo."""
        limiter = RateLimiter(max_requests=100, window_seconds=1)
        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            # Seed a bunch of transient IPs
            for i in range(50):
                limiter(_make_request(host=f"10.0.0.{i}"))
            assert len(limiter._requests) == 50

            # Advance past the window and the purge interval
            mock_time.monotonic.return_value = 1000.0 + 61.0
            # One more request triggers the periodic purge
            limiter(_make_request(host="10.0.0.99"))
            # All previously-stale IPs should be gone; only the fresh one remains
            assert list(limiter._requests.keys()) == ["10.0.0.99"]

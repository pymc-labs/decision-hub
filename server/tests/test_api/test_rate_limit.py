"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter


def _make_request(
    host: str = "127.0.0.1",
    *,
    forwarded_for: str | None = None,
    trusted_proxy: bool = False,
) -> MagicMock:
    """Create a mock Request with a given client IP and optional proxy state.

    The rate limiter resolves the client IP via :mod:`decision_hub.api.client_ip`,
    which inspects ``request.app.state.settings.trusted_proxy`` and the
    ``X-Forwarded-For`` header. We mock both here.
    """
    request = MagicMock()
    request.client = SimpleNamespace(host=host)
    request.app.state.settings = SimpleNamespace(trusted_proxy=trusted_proxy)
    headers: dict[str, str] = {}
    if forwarded_for is not None:
        headers["x-forwarded-for"] = forwarded_for
    request.headers = headers
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
        request = _make_request()
        request.client = None

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429

    # -----------------------------------------------------------------
    # Forwarded-header behaviour — the security-critical regression
    # this PR addresses. Behind Modal's load balancer every request
    # shares the LB's source address, so without honoring the proxy
    # header the per-IP limit would collapse into a global limit.
    # -----------------------------------------------------------------

    def test_forwarded_header_ignored_when_proxy_not_trusted(self) -> None:
        """X-Forwarded-For must NOT be honored unless trusted_proxy=True.

        Otherwise any caller could spoof their IP and bypass the limit.
        """
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        # All three requests share the same socket peer; spoofed XFF must
        # be ignored so they all map to the same key.
        spoofed = [_make_request("10.0.0.1", forwarded_for=f"203.0.113.{i}", trusted_proxy=False) for i in range(3)]
        limiter(spoofed[0])
        with pytest.raises(HTTPException):
            limiter(spoofed[1])
        with pytest.raises(HTTPException):
            limiter(spoofed[2])

    def test_forwarded_header_honored_when_proxy_trusted(self) -> None:
        """When trusted_proxy=True, X-Forwarded-For partitions the limit.

        Each origin client gets its own counter even though they share the
        load-balancer socket peer.
        """
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        a = _make_request("10.0.0.1", forwarded_for="203.0.113.10", trusted_proxy=True)
        b = _make_request("10.0.0.1", forwarded_for="203.0.113.11", trusted_proxy=True)
        limiter(a)
        limiter(b)  # different origin — should pass
        with pytest.raises(HTTPException):
            limiter(_make_request("10.0.0.1", forwarded_for="203.0.113.10", trusted_proxy=True))

    def test_forwarded_header_takes_leftmost_address(self) -> None:
        """X-Forwarded-For: 'client, proxy1, proxy2' uses 'client'."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        first = _make_request(
            "10.0.0.1",
            forwarded_for="203.0.113.10, 198.51.100.1, 198.51.100.2",
            trusted_proxy=True,
        )
        second = _make_request(
            "10.0.0.1",
            forwarded_for="203.0.113.10, 198.51.100.99, 198.51.100.42",
            trusted_proxy=True,
        )
        limiter(first)
        with pytest.raises(HTTPException):
            limiter(second)

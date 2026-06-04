"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, get_or_create_limiter


def _make_request(host: str = "127.0.0.1") -> MagicMock:
    """Create a mock Request with a given client IP."""
    request = MagicMock()
    request.client.host = host
    return request


class _FakeClock:
    """Deterministic clock for limiter purge / window tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, delta: float) -> None:
        self.t += delta


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


class TestRateLimiterPurge:
    """The limiter must trim stale IPs so memory stays bounded.

    Regression coverage for the previous ``total % 100 == 0`` purge
    heuristic, which never fired on traffic shapes that didn't hit an
    exact multiple of 100 active timestamps.
    """

    def test_stale_ips_are_purged_after_window(self) -> None:
        """IPs with no recent activity should be dropped from the table."""
        clock = _FakeClock()
        limiter = RateLimiter(max_requests=5, window_seconds=10, clock=clock)

        # 50 distinct IPs each issue one request.
        for i in range(50):
            limiter(_make_request(f"10.0.0.{i}"))
        assert len(limiter._requests) == 50

        # Advance past the window plus the half-window purge cadence,
        # then issue a single request from a new IP -- that call should
        # also trigger the purge sweep and drop every now-stale entry.
        clock.advance(16)
        limiter(_make_request("192.168.0.1"))
        assert len(limiter._requests) == 1
        assert "192.168.0.1" in limiter._requests

    def test_active_ips_are_not_purged(self) -> None:
        """IPs that issued a request inside the window survive a purge."""
        clock = _FakeClock()
        limiter = RateLimiter(max_requests=5, window_seconds=10, clock=clock)

        limiter(_make_request("active"))
        # Half a window later -- still inside the window, still active.
        clock.advance(5)
        limiter(_make_request("active"))
        # Cross the purge threshold; a new IP triggers the sweep.
        clock.advance(6)
        limiter(_make_request("trigger"))
        assert "active" in limiter._requests


class TestGetOrCreateLimiter:
    """The factory must lazily attach one limiter per name to app.state."""

    def test_returns_same_instance_for_same_name(self) -> None:
        state = SimpleNamespace()
        a = get_or_create_limiter(state, name="search", max_requests=10, window_seconds=60)
        b = get_or_create_limiter(state, name="search", max_requests=10, window_seconds=60)
        assert a is b

    def test_distinct_names_get_distinct_limiters(self) -> None:
        state = SimpleNamespace()
        a = get_or_create_limiter(state, name="search", max_requests=10, window_seconds=60)
        b = get_or_create_limiter(state, name="publish", max_requests=10, window_seconds=60)
        assert a is not b

    def test_subsequent_calls_ignore_changed_parameters(self) -> None:
        """The first call wins -- limiter parameters are not hot-reloaded.

        That matches the previous per-route ``hasattr`` behaviour and
        makes settings stable for the container lifetime.
        """
        state = SimpleNamespace()
        first = get_or_create_limiter(state, name="x", max_requests=5, window_seconds=60)
        second = get_or_create_limiter(state, name="x", max_requests=999, window_seconds=999)
        assert first is second
        assert second.max_requests == 5

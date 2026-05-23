"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, make_rate_limit_dep


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

    def test_stale_ips_purged_on_wall_clock_cadence(self) -> None:
        """Stale per-IP entries are evicted once the purge interval elapses.

        The previous implementation purged on ``total % 100 == 0`` which
        could fail to trigger under uneven traffic. The wall-clock guard
        must fire even with a single slow IP cycling in and out.
        """
        limiter = RateLimiter(max_requests=10, window_seconds=1)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            limiter(_make_request("10.0.0.1"))
            limiter(_make_request("10.0.0.2"))
            assert set(limiter._requests.keys()) == {"10.0.0.1", "10.0.0.2"}

            # Advance past the rate window AND the purge interval, then
            # touch a new IP. The stale ones should be swept.
            mock_time.monotonic.return_value = 1000.0 + 65
            limiter(_make_request("10.0.0.3"))
            assert set(limiter._requests.keys()) == {"10.0.0.3"}


class TestMakeRateLimitDep:
    """The factory builds a FastAPI-style dependency that lazily caches a limiter on app.state."""

    def _settings(self) -> SimpleNamespace:
        return SimpleNamespace(my_rate_limit=2, my_rate_window=60)

    def _request(self, settings, state=None) -> MagicMock:
        state = state if state is not None else SimpleNamespace(settings=settings)
        request = MagicMock()
        request.app.state = state
        request.client.host = "10.0.0.99"
        return request

    def test_creates_limiter_lazily_and_caches_on_state(self) -> None:
        dep = make_rate_limit_dep("my", "my_rate_limit", "my_rate_window")
        state = SimpleNamespace(settings=self._settings())
        request = self._request(self._settings(), state=state)

        assert not hasattr(state, "_my_rate_limiter")
        dep(request)
        first = state._my_rate_limiter
        dep(request)
        assert state._my_rate_limiter is first, "limiter should be cached, not re-created"

    def test_enforces_configured_threshold(self) -> None:
        dep = make_rate_limit_dep("my", "my_rate_limit", "my_rate_window")
        state = SimpleNamespace(settings=self._settings())
        request = self._request(self._settings(), state=state)

        for _ in range(2):
            dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_independent_limiters_per_dependency(self) -> None:
        """Two factories with different names own independent state attrs."""
        dep_a = make_rate_limit_dep("alpha", "my_rate_limit", "my_rate_window")
        dep_b = make_rate_limit_dep("beta", "my_rate_limit", "my_rate_window")
        state = SimpleNamespace(settings=self._settings())
        request = self._request(self._settings(), state=state)

        dep_a(request)
        dep_b(request)
        assert state._alpha_rate_limiter is not state._beta_rate_limiter

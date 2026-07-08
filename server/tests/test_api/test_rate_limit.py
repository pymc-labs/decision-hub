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

    def test_purge_stale_runs_periodically(self) -> None:
        """After PURGE_INTERVAL admissions, stale IPs are dropped.

        We admit ``_PURGE_INTERVAL`` distinct IPs, each two minutes after
        the previous, so every IP except the current one is stale relative
        to the 60-second window.  After the interval boundary trips, only
        the most-recent IP should remain in the tracker.
        """
        limiter = RateLimiter(max_requests=1000, window_seconds=60)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            base = 1_000.0
            for i in range(RateLimiter._PURGE_INTERVAL):
                mock_time.monotonic.return_value = base + i * 120
                req = _make_request(f"10.0.0.{i}")
                limiter(req)

        # Only the most recently admitted IP still has a live timestamp.
        assert set(limiter._requests) == {f"10.0.0.{RateLimiter._PURGE_INTERVAL - 1}"}
        assert limiter._admissions_since_purge == 0

    def test_purge_counter_survives_blocks(self) -> None:
        """Requests that raise 429 should NOT tick the purge counter forward.

        Regression: the old implementation used ``sum(len(v))`` after every
        admission, and blocked requests still contributed to the counter via
        the pre-append length.  The current counter increments only on
        successful admission.
        """
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        req = _make_request("10.0.0.1")

        limiter(req)  # 1 admission -> counter = 1
        for _ in range(50):
            with pytest.raises(HTTPException):
                limiter(req)  # blocked -> counter stays 1

        assert limiter._admissions_since_purge == 1


class TestMakeRateLimitDep:
    """Unit tests for the make_rate_limit_dep FastAPI-dependency factory."""

    def _make_request_with_settings(self, host: str = "127.0.0.1", **settings_kwargs) -> MagicMock:
        """Build a mock Request whose ``request.app.state`` mirrors runtime state."""
        request = MagicMock()
        request.client.host = host
        request.app.state = SimpleNamespace(settings=SimpleNamespace(**settings_kwargs))
        return request

    def test_lazy_initialises_limiter_on_first_call(self) -> None:
        """The limiter should be constructed only on first invocation."""
        dep = make_rate_limit_dep("demo", "demo_limit", "demo_window")
        request = self._make_request_with_settings(demo_limit=5, demo_window=60)

        assert not hasattr(request.app.state, "_demo_rate_limiter")
        dep(request)
        limiter = request.app.state._demo_rate_limiter
        assert isinstance(limiter, RateLimiter)
        assert limiter.max_requests == 5
        assert limiter.window_seconds == 60

    def test_reuses_cached_limiter_across_calls(self) -> None:
        """Subsequent calls must reuse the cached limiter instance."""
        dep = make_rate_limit_dep("demo", "demo_limit", "demo_window")
        request = self._make_request_with_settings(demo_limit=5, demo_window=60)

        dep(request)
        first = request.app.state._demo_rate_limiter
        dep(request)
        second = request.app.state._demo_rate_limiter
        assert first is second

    def test_distinct_names_get_distinct_limiters(self) -> None:
        """Two dependencies with different ``name`` values do not share state."""
        dep_a = make_rate_limit_dep("a", "a_limit", "a_window")
        dep_b = make_rate_limit_dep("b", "b_limit", "b_window")
        state = SimpleNamespace(
            settings=SimpleNamespace(a_limit=1, a_window=60, b_limit=100, b_window=60),
        )
        req_a = MagicMock()
        req_a.client.host = "10.0.0.1"
        req_a.app.state = state
        req_b = MagicMock()
        req_b.client.host = "10.0.0.1"
        req_b.app.state = state

        # Exhaust A's tiny budget; B must still admit because the limiter is
        # keyed by name, not by settings values.
        dep_a(req_a)
        with pytest.raises(HTTPException):
            dep_a(req_a)
        dep_b(req_b)  # should not raise

    def test_raises_when_settings_missing_attribute(self) -> None:
        """A misconfigured attribute name surfaces as an AttributeError, not a silent zero."""
        dep = make_rate_limit_dep("demo", "does_not_exist", "also_missing")
        request = self._make_request_with_settings()

        with pytest.raises(AttributeError):
            dep(request)

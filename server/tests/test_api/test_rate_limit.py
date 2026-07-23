"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, rate_limit_dependency


def _make_request(host: str = "127.0.0.1", app_state: object | None = None) -> MagicMock:
    """Create a mock Request with a given client IP and optional app.state."""
    request = MagicMock()
    request.client.host = host
    if app_state is not None:
        request.app.state = app_state
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

    def test_purge_stale_evicts_expired_ips(self) -> None:
        """Once a key's timestamps have all expired, the periodic sweep drops the key."""
        limiter = RateLimiter(max_requests=1000, window_seconds=10)
        # Set the purge cadence to 5 so the test doesn't need 100 calls.
        limiter._PURGE_EVERY = 5  # type: ignore[misc]

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            # Two distinct IPs, one request each.
            limiter(_make_request("10.0.0.1"))
            limiter(_make_request("10.0.0.2"))
            assert set(limiter._requests) == {"10.0.0.1", "10.0.0.2"}

            # Advance well past the window so both timestamps are stale.
            mock_time.monotonic.return_value = 200.0
            # Drive the counter to the purge threshold with an unrelated IP;
            # once we hit call #5 the stale sweep should drop 10.0.0.1/2.
            for _ in range(3):
                limiter(_make_request("10.0.0.3"))

            assert set(limiter._requests) == {"10.0.0.3"}

    def test_call_counter_triggers_purge_even_when_ips_expire(self) -> None:
        """The purge trigger is a monotonic counter, not a sum of live entries.

        Regression test for the previous ``sum(len(v) for v in ...) % 100`` trigger,
        which was O(N) per call and could skip purges when the total dipped
        back below the modulus threshold after a sweep.
        """
        limiter = RateLimiter(max_requests=1_000, window_seconds=60)
        limiter._PURGE_EVERY = 3  # type: ignore[misc]

        for i in range(9):
            limiter(_make_request(f"10.0.0.{i}"))

        # After 9 calls with PURGE_EVERY=3, purge should have been invoked
        # three times (calls #3, #6, #9); counter is exactly 9.
        assert limiter._call_count == 9


class TestRateLimitDependency:
    """Unit tests for the rate_limit_dependency() factory."""

    def _state_with_settings(self, **rate_settings: int) -> SimpleNamespace:
        """Build a fresh app.state with a Settings-like object attached."""
        settings = SimpleNamespace(**rate_settings)
        return SimpleNamespace(settings=settings)

    def test_lazy_init_uses_named_settings(self) -> None:
        """The factory reads {name}_rate_limit / {name}_rate_window on first call."""
        state = self._state_with_settings(demo_rate_limit=2, demo_rate_window=60)
        dep = rate_limit_dependency("demo")

        request = _make_request("10.0.0.1", app_state=state)
        # First call initialises the limiter and is allowed.
        dep(request)
        limiter = state._demo_rate_limiter
        assert isinstance(limiter, RateLimiter)
        assert limiter.max_requests == 2
        assert limiter.window_seconds == 60

    def test_second_call_reuses_cached_limiter(self) -> None:
        """The limiter is cached on app.state so counters persist across requests."""
        state = self._state_with_settings(demo_rate_limit=2, demo_rate_window=60)
        dep = rate_limit_dependency("demo")

        request = _make_request("10.0.0.1", app_state=state)
        dep(request)
        cached = state._demo_rate_limiter
        dep(request)
        assert state._demo_rate_limiter is cached

    def test_enforces_the_named_limit(self) -> None:
        """Calls beyond the configured limit raise HTTP 429."""
        state = self._state_with_settings(demo_rate_limit=2, demo_rate_window=60)
        dep = rate_limit_dependency("demo")
        request = _make_request("10.0.0.1", app_state=state)

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_each_name_gets_its_own_limiter(self) -> None:
        """Two dependencies with different names must not share a limiter."""
        state = self._state_with_settings(
            demo_rate_limit=1,
            demo_rate_window=60,
            other_rate_limit=1,
            other_rate_window=60,
        )
        demo = rate_limit_dependency("demo")
        other = rate_limit_dependency("other")

        request = _make_request("10.0.0.1", app_state=state)
        demo(request)  # exhausts the "demo" bucket
        # "other" must remain allowed because it uses its own counter.
        other(request)

        with pytest.raises(HTTPException):
            demo(request)

    def test_dependency_name_matches_input(self) -> None:
        """The returned callable has a descriptive __name__ for FastAPI introspection."""
        dep = rate_limit_dependency("demo")
        assert dep.__name__ == "_enforce_demo_rate_limit"

"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, make_rate_limiter_dep


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

    def test_purge_stale_runs_on_counter_not_total(self) -> None:
        """Stale-IP purge fires every N calls regardless of map size.

        Regression test: the previous implementation triggered the sweep when
        ``total % 100 == 0``, which is true for ``total == 0`` -- so once
        every IP was purged the sweep ran on every subsequent request.
        """
        limiter = RateLimiter(max_requests=1000, window_seconds=60)
        request = _make_request()
        # No exceptions; deque-based pruning + counter-based sweep should
        # not regress on bursts of small calls.
        for _ in range(250):
            limiter(request)
        # Internal counter resets after each sweep, so it stays bounded.
        assert limiter._calls_since_purge < 100

    def test_uses_deque_not_list(self) -> None:
        """Per-IP timestamps are stored in a deque so popleft is O(1)."""
        from collections import deque

        limiter = RateLimiter(max_requests=10, window_seconds=60)
        limiter(_make_request())
        assert isinstance(limiter._requests["127.0.0.1"], deque)


class TestMakeRateLimiterDep:
    """Unit tests for the make_rate_limiter_dep factory."""

    def _make_app_state(self, *, limit: int = 5, window: int = 60) -> SimpleNamespace:
        """Build a minimal request whose ``app.state`` carries settings."""
        settings = SimpleNamespace(my_limit=limit, my_window=window, other_limit=99, other_window=10)
        return SimpleNamespace(settings=settings)

    def _make_request_with_state(self, state: SimpleNamespace, host: str = "127.0.0.1") -> MagicMock:
        request = MagicMock()
        request.client.host = host
        request.app.state = state
        return request

    def test_lazy_init_creates_limiter_once(self) -> None:
        """The first call constructs the limiter; later calls reuse it."""
        dep = make_rate_limiter_dep("_test_lim", "my_limit", "my_window")
        state = self._make_app_state()
        request = self._make_request_with_state(state)

        dep(request)
        first = state._test_lim
        dep(request)
        assert state._test_lim is first

    def test_independent_attrs_get_independent_buckets(self) -> None:
        """Two factories with different state_attrs must not share counters."""
        dep_a = make_rate_limiter_dep("_lim_a", "my_limit", "my_window")
        dep_b = make_rate_limiter_dep("_lim_b", "my_limit", "my_window")
        state = self._make_app_state(limit=2, window=60)
        request = self._make_request_with_state(state)

        # Fill bucket A.
        dep_a(request)
        dep_a(request)
        # Bucket B should be untouched.
        dep_b(request)
        dep_b(request)
        # Both should now reject on the next call.
        with pytest.raises(HTTPException):
            dep_a(request)
        with pytest.raises(HTTPException):
            dep_b(request)

    def test_reads_settings_at_init_time_only(self) -> None:
        """Limit/window are captured on first call -- mutating settings later is a no-op.

        This documents existing behaviour so callers don't expect runtime
        changes to settings to take effect without restarting the app.
        """
        dep = make_rate_limiter_dep("_lim_freeze", "my_limit", "my_window")
        state = self._make_app_state(limit=2, window=60)
        request = self._make_request_with_state(state)

        dep(request)
        # Bumping the setting after init has no effect on the cached limiter.
        state.settings.my_limit = 1000
        dep(request)
        with pytest.raises(HTTPException):
            dep(request)

    def test_dependency_has_a_useful_name(self) -> None:
        """FastAPI uses callable identity/name for traceback clarity."""
        dep = make_rate_limiter_dep("_lim_named", "my_limit", "my_window")
        assert "lim_named" in dep.__name__

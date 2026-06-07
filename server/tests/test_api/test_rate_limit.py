"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, make_rate_limit_dependency


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


def _make_state_request(state: SimpleNamespace, host: str = "10.0.0.1") -> MagicMock:
    """Mock a Request whose ``app.state`` is the given SimpleNamespace."""
    request = MagicMock()
    request.client.host = host
    request.app.state = state
    return request


class TestMakeRateLimitDependency:
    """Unit tests for the FastAPI-dependency factory."""

    def test_caches_limiter_on_app_state(self) -> None:
        """First call creates a RateLimiter on state; subsequent calls reuse it."""
        settings = SimpleNamespace(my_rate_limit=5, my_rate_window=60)
        state = SimpleNamespace(settings=settings)
        dep = make_rate_limit_dependency(
            "my",
            max_requests_setting="my_rate_limit",
            window_seconds_setting="my_rate_window",
        )

        dep(_make_state_request(state))
        first_limiter = state._my_rate_limiter
        dep(_make_state_request(state))
        assert state._my_rate_limiter is first_limiter

    def test_reads_bounds_from_named_settings(self) -> None:
        """The factory binds to the named settings attributes, not magic globals."""
        settings = SimpleNamespace(foo_limit=2, foo_window=60)
        state = SimpleNamespace(settings=settings)
        dep = make_rate_limit_dependency(
            "foo",
            max_requests_setting="foo_limit",
            window_seconds_setting="foo_window",
        )

        # First 2 succeed, third must 429.
        dep(_make_state_request(state))
        dep(_make_state_request(state))
        with pytest.raises(HTTPException) as exc_info:
            dep(_make_state_request(state))
        assert exc_info.value.status_code == 429

    def test_independent_dependencies_have_independent_buckets(self) -> None:
        """Two dependencies on the same app state must not share a budget."""
        settings = SimpleNamespace(a_limit=1, a_window=60, b_limit=1, b_window=60)
        state = SimpleNamespace(settings=settings)
        dep_a = make_rate_limit_dependency("a", max_requests_setting="a_limit", window_seconds_setting="a_window")
        dep_b = make_rate_limit_dependency("b", max_requests_setting="b_limit", window_seconds_setting="b_window")

        dep_a(_make_state_request(state))
        # Hitting dep_b a single time must not blow A's already-spent budget.
        dep_b(_make_state_request(state))

    def test_debuggable_callable_name(self) -> None:
        """The closure has a human-readable name for tracebacks and OpenAPI."""
        dep = make_rate_limit_dependency("things", max_requests_setting="x", window_seconds_setting="y")
        assert dep.__name__ == "enforce_things_rate_limit"

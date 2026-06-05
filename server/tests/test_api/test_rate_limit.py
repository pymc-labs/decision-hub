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


class TestMakeRateLimitDep:
    """Unit tests for the ``make_rate_limit_dep`` factory.

    The factory replaced 9 nearly-identical ``_enforce_<name>_rate_limit``
    helpers across the route modules.  Each dependency must:
        - lazily build a RateLimiter on first call,
        - cache that limiter on ``request.app.state`` so subsequent
          requests reuse the same in-memory window,
        - read max_requests / window_seconds from named settings
          attributes so different endpoints can have different budgets,
        - delegate to the cached limiter to enforce the limit.
    """

    def _make_request_with_state(self, settings, host: str = "127.0.0.1"):
        state = SimpleNamespace(settings=settings)
        request = MagicMock()
        request.app.state = state
        request.client.host = host
        return request, state

    def test_lazy_construction_reads_settings(self) -> None:
        """The limiter is built lazily on first call using the named settings attrs."""
        settings = SimpleNamespace(my_max=3, my_window=60)
        dep = make_rate_limit_dep("my_endpoint", "my_max", "my_window")
        request, state = self._make_request_with_state(settings)

        # Before first call: nothing cached on state
        assert not hasattr(state, "_my_endpoint_rate_limiter")

        dep(request)

        limiter = state._my_endpoint_rate_limiter
        assert isinstance(limiter, RateLimiter)
        assert limiter.max_requests == 3
        assert limiter.window_seconds == 60

    def test_cached_limiter_is_reused(self) -> None:
        """Subsequent calls reuse the same RateLimiter instance from app.state."""
        settings = SimpleNamespace(my_max=5, my_window=60)
        dep = make_rate_limit_dep("reuse_test", "my_max", "my_window")
        request, state = self._make_request_with_state(settings)

        dep(request)
        first = state._reuse_test_rate_limiter
        dep(request)
        second = state._reuse_test_rate_limiter

        assert first is second

    def test_enforces_limit_through_cached_limiter(self) -> None:
        """The dependency enforces the budget across many calls."""
        settings = SimpleNamespace(strict_max=2, strict_window=60)
        dep = make_rate_limit_dep("strict", "strict_max", "strict_window")
        request, _ = self._make_request_with_state(settings)

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_separate_names_get_separate_limiters(self) -> None:
        """Two factory-built deps using the same settings still get isolated state."""
        settings = SimpleNamespace(s_max=1, s_window=60)
        dep_a = make_rate_limit_dep("alpha", "s_max", "s_window")
        dep_b = make_rate_limit_dep("beta", "s_max", "s_window")
        request, state = self._make_request_with_state(settings)

        dep_a(request)  # consumes alpha's budget
        dep_b(request)  # beta's budget is independent

        # alpha is exhausted
        with pytest.raises(HTTPException):
            dep_a(request)
        # beta is exhausted too (separate counter)
        with pytest.raises(HTTPException):
            dep_b(request)

        assert state._alpha_rate_limiter is not state._beta_rate_limiter

    def test_function_name_is_meaningful(self) -> None:
        """``__name__`` is set so FastAPI debug traces stay readable."""
        dep = make_rate_limit_dep("readable_trace", "x", "y")
        assert dep.__name__ == "enforce_readable_trace_rate_limit"
        assert "readable_trace" in (dep.__doc__ or "")

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


class TestMakeRateLimitDependency:
    """Tests for the lazy-init factory used by every rate-limited route."""

    def _make_request_with_state(self, settings_kwargs: dict, host: str = "1.2.3.4"):
        """Build a fake Request whose ``app.state`` carries the given settings.

        The factory pulls limits off ``request.app.state.settings`` and stashes
        the limiter on ``request.app.state``, so we mirror that surface area
        with a ``SimpleNamespace`` instead of pulling the whole FastAPI app.
        """
        state = SimpleNamespace(settings=SimpleNamespace(**settings_kwargs))
        app = SimpleNamespace(state=state)
        request = MagicMock()
        request.app = app
        request.client.host = host
        return request, state

    def test_lazy_initializes_limiter_on_state(self) -> None:
        """First call attaches a RateLimiter to ``app.state._<name>_rate_limiter``."""
        dep = make_rate_limit_dependency("widget", "widget_rate_limit", "widget_rate_window")
        request, state = self._make_request_with_state({"widget_rate_limit": 3, "widget_rate_window": 60})

        assert not hasattr(state, "_widget_rate_limiter")
        dep(request)
        limiter = state._widget_rate_limiter
        assert isinstance(limiter, RateLimiter)
        assert limiter.max_requests == 3
        assert limiter.window_seconds == 60

    def test_reuses_limiter_across_calls(self) -> None:
        """Subsequent calls hit the same limiter instance (state shared per-app)."""
        dep = make_rate_limit_dependency("widget", "widget_rate_limit", "widget_rate_window")
        request, state = self._make_request_with_state({"widget_rate_limit": 3, "widget_rate_window": 60})

        dep(request)
        first = state._widget_rate_limiter
        dep(request)
        assert state._widget_rate_limiter is first

    def test_enforces_429_after_budget_exhausted(self) -> None:
        """The dependency surfaces the underlying RateLimiter's HTTP 429."""
        dep = make_rate_limit_dependency("widget", "widget_rate_limit", "widget_rate_window")
        request, _state = self._make_request_with_state({"widget_rate_limit": 2, "widget_rate_window": 60})

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc:
            dep(request)
        assert exc.value.status_code == 429

    def test_distinct_names_get_independent_limiters(self) -> None:
        """Two dependencies with different names share neither budget nor state."""
        dep_a = make_rate_limit_dependency("alpha", "alpha_rate_limit", "alpha_rate_window")
        dep_b = make_rate_limit_dependency("beta", "beta_rate_limit", "beta_rate_window")
        request, state = self._make_request_with_state(
            {
                "alpha_rate_limit": 1,
                "alpha_rate_window": 60,
                "beta_rate_limit": 5,
                "beta_rate_window": 60,
            }
        )

        dep_a(request)
        with pytest.raises(HTTPException):
            dep_a(request)
        # Beta has its own bucket and is unaffected.
        dep_b(request)
        assert state._alpha_rate_limiter is not state._beta_rate_limiter

    def test_dependency_name_is_stable_for_fastapi(self) -> None:
        """Dependency must expose a stable ``__name__`` so FastAPI / OpenAPI render it predictably."""
        dep = make_rate_limit_dependency("widget", "widget_rate_limit", "widget_rate_window")
        assert dep.__name__ == "_enforce_widget_rate_limit"
        assert dep.__qualname__ == "_enforce_widget_rate_limit"

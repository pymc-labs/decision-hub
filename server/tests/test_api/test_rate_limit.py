"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter


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
    """The factory must build a dependency that lazily caches the limiter on app.state.

    Behaviour we lock down:
    - First call constructs a RateLimiter from settings.{name}_rate_limit /
      .{name}_rate_window and stores it on app.state under a stable key.
    - Subsequent calls reuse the same instance (so request counts persist
      across requests rather than resetting on every dependency invocation).
    - Two distinct names get two distinct cache slots and do not interfere.
    - Once cached, the limiter enforces its limit (boundary check + 429).
    """

    def _state(self, **rates: int) -> MagicMock:
        """Build a fake app.state whose .settings carries the named limits."""
        state = MagicMock(spec_set=["settings"])
        settings = MagicMock()
        for k, v in rates.items():
            setattr(settings, k, v)
        state.settings = settings
        # Strip any pre-populated `_rate_limiter__*` attrs so getattr returns
        # None and the factory takes its initialisation branch.
        return state

    def _request(self, state: MagicMock, host: str = "127.0.0.1") -> MagicMock:
        request = MagicMock()
        request.app.state = state
        request.client.host = host
        return request

    def test_caches_limiter_on_app_state(self) -> None:
        from decision_hub.api.rate_limit import make_rate_limit_dep

        dep = make_rate_limit_dep("widget")
        # MagicMock's getattr-with-default returns a Mock by default, so we
        # need a plain object whose attribute lookups raise AttributeError.
        state = type("S", (), {})()
        state.settings = type("Sett", (), {"widget_rate_limit": 5, "widget_rate_window": 60})()
        request = MagicMock()
        request.app.state = state
        request.client.host = "10.0.0.1"

        dep(request)
        first = state._rate_limiter__widget
        dep(request)
        second = state._rate_limiter__widget

        assert isinstance(first, RateLimiter)
        assert first is second, "limiter must be reused across calls — not rebuilt per request"
        assert first.max_requests == 5
        assert first.window_seconds == 60

    def test_distinct_names_get_distinct_limiters(self) -> None:
        from decision_hub.api.rate_limit import make_rate_limit_dep

        dep_a = make_rate_limit_dep("alpha")
        dep_b = make_rate_limit_dep("beta")
        state = type("S", (), {})()
        state.settings = type(
            "Sett",
            (),
            {
                "alpha_rate_limit": 3,
                "alpha_rate_window": 60,
                "beta_rate_limit": 7,
                "beta_rate_window": 30,
            },
        )()
        request = MagicMock()
        request.app.state = state
        request.client.host = "10.0.0.1"

        dep_a(request)
        dep_b(request)

        assert state._rate_limiter__alpha is not state._rate_limiter__beta
        assert state._rate_limiter__alpha.max_requests == 3
        assert state._rate_limiter__beta.max_requests == 7

    def test_enforces_configured_limit_after_caching(self) -> None:
        from decision_hub.api.rate_limit import make_rate_limit_dep

        dep = make_rate_limit_dep("burst")
        state = type("S", (), {})()
        state.settings = type("Sett", (), {"burst_rate_limit": 2, "burst_rate_window": 60})()
        request = MagicMock()
        request.app.state = state
        request.client.host = "10.0.0.1"

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

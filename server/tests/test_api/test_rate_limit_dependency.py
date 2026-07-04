"""Tests for the rate_limit_dependency factory."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, rate_limit_dependency


def _make_request(app_state: MagicMock, host: str = "127.0.0.1") -> MagicMock:
    """Build a mock Request that shares state with a MagicMock app."""
    request = MagicMock()
    request.client.host = host
    request.app.state = app_state
    return request


class TestRateLimitDependency:
    """The factory should read settings once, cache the limiter, and enforce it."""

    def test_lazily_initialises_limiter_from_settings(self) -> None:
        """First call reads settings.foo_rate_limit/foo_rate_window and stashes a limiter."""
        state = MagicMock(spec=[])  # no pre-set attributes
        state.settings = MagicMock()
        state.settings.foo_rate_limit = 5
        state.settings.foo_rate_window = 60

        dep = rate_limit_dependency("foo")
        dep(_make_request(state))

        assert isinstance(state._foo_rate_limiter, RateLimiter)
        assert state._foo_rate_limiter.max_requests == 5
        assert state._foo_rate_limiter.window_seconds == 60

    def test_reuses_the_same_limiter_across_calls(self) -> None:
        """Subsequent calls hit the cached limiter (no repeated settings reads)."""
        state = MagicMock(spec=[])
        state.settings = MagicMock()
        state.settings.foo_rate_limit = 5
        state.settings.foo_rate_window = 60

        dep = rate_limit_dependency("foo")
        dep(_make_request(state))
        first = state._foo_rate_limiter
        dep(_make_request(state))
        second = state._foo_rate_limiter

        assert first is second

    def test_raises_429_when_limit_is_exceeded(self) -> None:
        """The N+1th request within the window returns 429."""
        state = MagicMock(spec=[])
        state.settings = MagicMock()
        state.settings.foo_rate_limit = 2
        state.settings.foo_rate_window = 60

        dep = rate_limit_dependency("foo")
        request = _make_request(state)

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_different_names_have_independent_limiters(self) -> None:
        """Two deps built from different names must not share state."""
        state = MagicMock(spec=[])
        state.settings = MagicMock()
        state.settings.foo_rate_limit = 1
        state.settings.foo_rate_window = 60
        state.settings.bar_rate_limit = 1
        state.settings.bar_rate_window = 60

        foo = rate_limit_dependency("foo")
        bar = rate_limit_dependency("bar")

        request = _make_request(state)
        foo(request)
        # foo is now at its limit but bar should still be free.
        bar(request)  # must not raise

        with pytest.raises(HTTPException):
            foo(request)

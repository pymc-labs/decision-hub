"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, rate_limit_dependency


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


def _fake_settings(max_requests: int, window_seconds: int) -> SimpleNamespace:
    return SimpleNamespace(
        limit=max_requests,
        window=window_seconds,
    )


def _fake_request(state: SimpleNamespace, host: str = "127.0.0.1") -> MagicMock:
    request = MagicMock()
    request.app.state = state
    request.client.host = host
    return request


class TestRateLimitDependencyFactory:
    """The factory that replaced 8 near-identical `_enforce_*_rate_limit`
    functions across the codebase. Its behaviour must exactly match the
    old copy-pasted implementations."""

    def test_lazy_init_creates_one_limiter_per_name(self) -> None:
        settings = _fake_settings(3, 60)
        state = SimpleNamespace(settings=settings)
        dep = rate_limit_dependency("_test_limiter", lambda s: (s.limit, s.window))

        assert not hasattr(state, "_test_limiter")
        dep(_fake_request(state))
        assert hasattr(state, "_test_limiter")
        first = state._test_limiter
        # Subsequent calls reuse the same limiter object.
        dep(_fake_request(state))
        assert state._test_limiter is first

    def test_enforces_configured_limit(self) -> None:
        settings = _fake_settings(2, 60)
        state = SimpleNamespace(settings=settings)
        dep = rate_limit_dependency("_test_enf", lambda s: (s.limit, s.window))

        req = _fake_request(state)
        dep(req)
        dep(req)
        with pytest.raises(HTTPException) as exc_info:
            dep(req)
        assert exc_info.value.status_code == 429

    def test_two_dependencies_are_independent(self) -> None:
        """Different attr_names must produce independent limiters — the
        old code kept `_search_rate_limiter` and `_publish_rate_limiter`
        separate; the factory must do the same."""
        settings = _fake_settings(1, 60)
        state = SimpleNamespace(settings=settings)
        dep_a = rate_limit_dependency("_a_lim", lambda s: (s.limit, s.window))
        dep_b = rate_limit_dependency("_b_lim", lambda s: (s.limit, s.window))

        req = _fake_request(state)
        dep_a(req)
        # `dep_a` is now full; `dep_b` should still pass because it has its
        # own bucket.
        dep_b(req)
        with pytest.raises(HTTPException):
            dep_a(req)

    def test_settings_getter_receives_settings(self) -> None:
        """The getter must be called with the app's `Settings` instance."""
        settings = _fake_settings(5, 30)
        state = SimpleNamespace(settings=settings)
        captured: list = []

        def _getter(s):
            captured.append(s)
            return s.limit, s.window

        dep = rate_limit_dependency("_capt_lim", _getter)
        dep(_fake_request(state))
        assert captured == [settings]
        assert state._capt_lim.max_requests == 5
        assert state._capt_lim.window_seconds == 30

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


def _make_request_with_state(state: SimpleNamespace, host: str = "127.0.0.1") -> MagicMock:
    """Create a mock Request whose ``app.state`` is the given namespace."""
    request = MagicMock()
    request.client.host = host
    request.app.state = state
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


class TestMakeRateLimiterDep:
    """The factory should derive settings from the name and memoise the limiter."""

    def test_reads_settings_by_convention(self) -> None:
        """The factory looks up ``<name>_rate_limit`` and ``<name>_rate_window`` on settings."""
        settings = SimpleNamespace(foo_rate_limit=2, foo_rate_window=60)
        state = SimpleNamespace(settings=settings)
        dep = make_rate_limiter_dep("foo")
        request = _make_request_with_state(state)

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_memoises_limiter_on_app_state(self) -> None:
        """Repeated calls reuse the same limiter instance stored on ``app.state``."""
        settings = SimpleNamespace(bar_rate_limit=5, bar_rate_window=60)
        state = SimpleNamespace(settings=settings)
        dep = make_rate_limiter_dep("bar")
        request = _make_request_with_state(state)

        dep(request)
        first = state._bar_rate_limiter
        dep(request)
        second = state._bar_rate_limiter

        assert first is second
        assert isinstance(first, RateLimiter)
        assert first.max_requests == 5
        assert first.window_seconds == 60

    def test_separate_names_get_independent_limiters(self) -> None:
        """Two factories with different names produce two independent limiters."""
        settings = SimpleNamespace(
            a_rate_limit=1,
            a_rate_window=60,
            b_rate_limit=1,
            b_rate_window=60,
        )
        state = SimpleNamespace(settings=settings)
        dep_a = make_rate_limiter_dep("a")
        dep_b = make_rate_limiter_dep("b")
        request = _make_request_with_state(state)

        dep_a(request)
        # ``a`` is now full but ``b`` should still allow one request.
        with pytest.raises(HTTPException):
            dep_a(request)
        dep_b(request)
        with pytest.raises(HTTPException):
            dep_b(request)

        assert state._a_rate_limiter is not state._b_rate_limiter

    def test_dependency_has_descriptive_name(self) -> None:
        """The generated callable carries a useful ``__name__`` for tracebacks/docs."""
        dep = make_rate_limiter_dep("baz")
        assert dep.__name__ == "_enforce_baz_rate_limit"

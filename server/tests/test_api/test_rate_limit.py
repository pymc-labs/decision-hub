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


def _request_with_state(state: SimpleNamespace, host: str = "127.0.0.1") -> MagicMock:
    """Build a mock Request whose ``app.state`` is the given namespace."""
    request = MagicMock()
    request.client.host = host
    request.app.state = state
    return request


class TestMakeRateLimitDep:
    """Unit tests for the make_rate_limit_dep factory."""

    def test_lazily_instantiates_limiter_from_settings(self) -> None:
        """First request reads max_requests / window_seconds from settings."""
        settings = SimpleNamespace(foo_rate_limit=3, foo_rate_window=60)
        state = SimpleNamespace(settings=settings)
        request = _request_with_state(state)

        dep = make_rate_limit_dep("foo")
        for _ in range(3):
            dep(request)

        limiter = state._foo_rate_limiter
        assert isinstance(limiter, RateLimiter)
        assert limiter.max_requests == 3
        assert limiter.window_seconds == 60

    def test_reuses_cached_limiter_across_requests(self) -> None:
        """The limiter is built once and reused, so per-IP counts persist."""
        settings = SimpleNamespace(foo_rate_limit=2, foo_rate_window=60)
        state = SimpleNamespace(settings=settings)
        request = _request_with_state(state)

        dep = make_rate_limit_dep("foo")
        dep(request)
        first_limiter = state._foo_rate_limiter
        dep(request)
        assert state._foo_rate_limiter is first_limiter

        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_distinct_names_get_independent_limiters(self) -> None:
        """Each name maps to its own settings keys and its own state attribute."""
        settings = SimpleNamespace(
            foo_rate_limit=1,
            foo_rate_window=60,
            bar_rate_limit=5,
            bar_rate_window=60,
        )
        state = SimpleNamespace(settings=settings)
        request = _request_with_state(state)

        foo = make_rate_limit_dep("foo")
        bar = make_rate_limit_dep("bar")

        foo(request)
        # foo is now exhausted ...
        with pytest.raises(HTTPException):
            foo(request)
        # ... but bar is independent and still wide open.
        for _ in range(5):
            bar(request)
        assert state._foo_rate_limiter is not state._bar_rate_limiter

    def test_dep_name_reflects_rate_limit_name(self) -> None:
        """The returned dep advertises a clear __name__ for tracebacks/debug."""
        dep = make_rate_limit_dep("publish")
        assert dep.__name__ == "_enforce_publish_rate_limit"

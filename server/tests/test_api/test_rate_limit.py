"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, lazy_rate_limiter


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


class TestLazyRateLimiter:
    """Tests for the ``lazy_rate_limiter`` factory used by route dependencies."""

    @staticmethod
    def _make_request(host: str = "1.2.3.4") -> MagicMock:
        request = MagicMock()
        request.client.host = host
        # SimpleNamespace lets the dependency mutate state via setattr().
        request.app.state = SimpleNamespace(
            settings=SimpleNamespace(foo_rate_limit=2, foo_rate_window=60),
        )
        return request

    def test_initialises_limiter_lazily_from_settings(self) -> None:
        """First call constructs the limiter from <name>_rate_limit/window settings."""
        dep = lazy_rate_limiter("foo")
        request = self._make_request()

        # Before any call, no limiter is cached on app state.
        assert not hasattr(request.app.state, "_foo_rate_limiter")

        dep(request)

        cached = request.app.state._foo_rate_limiter
        assert isinstance(cached, RateLimiter)
        assert cached.max_requests == 2
        assert cached.window_seconds == 60

    def test_reuses_cached_limiter_across_calls(self) -> None:
        """Subsequent calls reuse the cached limiter so counters accumulate per IP."""
        dep = lazy_rate_limiter("foo")
        request = self._make_request()

        dep(request)
        first = request.app.state._foo_rate_limiter
        dep(request)
        second = request.app.state._foo_rate_limiter
        assert first is second

        # Third call exceeds max_requests=2 → 429.
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_two_names_get_independent_limiters(self) -> None:
        """Limiters for different ``name`` keys are isolated on app state."""
        foo = lazy_rate_limiter("foo")
        bar = lazy_rate_limiter("bar")
        request = MagicMock()
        request.client.host = "9.9.9.9"
        request.app.state = SimpleNamespace(
            settings=SimpleNamespace(
                foo_rate_limit=1,
                foo_rate_window=60,
                bar_rate_limit=10,
                bar_rate_window=60,
            ),
        )

        foo(request)
        # foo is now at its 1-request limit; bar is unaffected.
        with pytest.raises(HTTPException):
            foo(request)
        bar(request)  # should not raise

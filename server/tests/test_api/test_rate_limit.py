"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import (
    RateLimiter,
    enforce_rate_limit,
    make_rate_limit_dep,
)


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
    """Build a Request mock with both ``client.host`` and ``app.state``."""
    request = MagicMock()
    request.client.host = host
    request.app.state = state
    return request


class TestEnforceRateLimit:
    """Unit tests for the named ``enforce_rate_limit`` helper."""

    def test_creates_limiter_on_first_call(self) -> None:
        """A fresh state has no cached limiter; the helper builds one."""
        state = SimpleNamespace()
        request = _request_with_state(state)

        enforce_rate_limit(request, name="bucket", max_requests=5, window_seconds=60)

        assert isinstance(state._rate_limiter_bucket, RateLimiter)
        assert state._rate_limiter_bucket.max_requests == 5

    def test_reuses_limiter_across_calls(self) -> None:
        """Subsequent calls reuse the cached limiter (counters accumulate)."""
        state = SimpleNamespace()
        request = _request_with_state(state)

        for _ in range(3):
            enforce_rate_limit(request, name="bucket", max_requests=3, window_seconds=60)

        with pytest.raises(HTTPException) as exc_info:
            enforce_rate_limit(request, name="bucket", max_requests=3, window_seconds=60)
        assert exc_info.value.status_code == 429

    def test_separate_named_buckets_are_independent(self) -> None:
        """Two different names give two different limiters that don't share quota."""
        state = SimpleNamespace()
        request = _request_with_state(state)

        for _ in range(2):
            enforce_rate_limit(request, name="alpha", max_requests=2, window_seconds=60)
        for _ in range(2):
            enforce_rate_limit(request, name="beta", max_requests=2, window_seconds=60)

        # alpha is exhausted; beta is exhausted; both raise independently
        with pytest.raises(HTTPException):
            enforce_rate_limit(request, name="alpha", max_requests=2, window_seconds=60)
        with pytest.raises(HTTPException):
            enforce_rate_limit(request, name="beta", max_requests=2, window_seconds=60)


class TestMakeRateLimitDep:
    """Unit tests for the FastAPI-dependency factory."""

    def test_reads_settings_at_call_time(self) -> None:
        """The dep looks up settings via attribute names on each invocation,
        so changing the underlying settings between calls is respected."""
        settings = SimpleNamespace(my_limit=2, my_window=60)
        state = SimpleNamespace(settings=settings)
        request = _request_with_state(state)
        dep = make_rate_limit_dep("ratebucket", "my_limit", "my_window")

        # First two requests pass; third hits 429
        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_distinct_dep_names_dont_collide(self) -> None:
        """Two deps with different names share an app state without colliding."""
        settings = SimpleNamespace(a_limit=1, a_window=60, b_limit=2, b_window=60)
        state = SimpleNamespace(settings=settings)
        request = _request_with_state(state)
        dep_a = make_rate_limit_dep("alpha", "a_limit", "a_window")
        dep_b = make_rate_limit_dep("beta", "b_limit", "b_window")

        dep_a(request)
        with pytest.raises(HTTPException):
            dep_a(request)  # alpha exhausted

        # beta is independent and still has quota
        dep_b(request)
        dep_b(request)
        with pytest.raises(HTTPException):
            dep_b(request)

    def test_dep_has_friendly_name(self) -> None:
        """The returned callable picks up an ``__name__`` so FastAPI traces
        are readable instead of saying ``_dep``."""
        dep = make_rate_limit_dep("publish", "publish_rate_limit", "publish_rate_window")
        assert dep.__name__ == "_enforce_publish_rate_limit"

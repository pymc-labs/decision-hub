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


def _make_request_with_state(state: SimpleNamespace, host: str = "127.0.0.1") -> MagicMock:
    """Build a mock request whose ``app.state`` shares a single state object.

    Two requests built from the same ``state`` namespace see the same lazy
    limiter instance — that's how the factory caches across requests in real
    FastAPI usage.
    """
    request = MagicMock()
    request.client.host = host
    request.app.state = state
    return request


class TestMakeRateLimiterDep:
    """Unit tests for the make_rate_limiter_dep factory."""

    def test_lazy_init_reads_settings_fields(self) -> None:
        """The factory pulls limit + window from the named Settings fields on first use."""
        settings = SimpleNamespace(my_limit=2, my_window=60)
        state = SimpleNamespace(settings=settings)
        dep = make_rate_limiter_dep("my_limit", "my_window")
        request = _make_request_with_state(state)

        for _ in range(2):
            dep(request)

        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_limiter_is_cached_on_state(self) -> None:
        """Repeated calls share one limiter cached on app.state."""
        settings = SimpleNamespace(my_limit=5, my_window=60)
        state = SimpleNamespace(settings=settings)
        dep = make_rate_limiter_dep("my_limit", "my_window")
        request = _make_request_with_state(state)

        dep(request)
        first = state._rate_limiter__my_limit__my_window
        dep(request)
        second = state._rate_limiter__my_limit__my_window
        assert first is second
        assert isinstance(first, RateLimiter)

    def test_distinct_field_pairs_get_distinct_limiters(self) -> None:
        """Two deps built from different field names cache under different keys."""
        settings = SimpleNamespace(a_limit=1, a_window=60, b_limit=1, b_window=60)
        state = SimpleNamespace(settings=settings)
        dep_a = make_rate_limiter_dep("a_limit", "a_window")
        dep_b = make_rate_limiter_dep("b_limit", "b_window")
        request = _make_request_with_state(state)

        dep_a(request)  # consumes a's only slot
        dep_b(request)  # consumes b's only slot; independent

        with pytest.raises(HTTPException):
            dep_a(request)
        with pytest.raises(HTTPException):
            dep_b(request)

    def test_dep_name_includes_limit_field(self) -> None:
        """The generated dependency carries a descriptive __name__ for debugging."""
        dep = make_rate_limiter_dep("publish_rate_limit", "publish_rate_window")
        assert "publish_rate_limit" in dep.__name__

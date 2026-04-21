"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, rate_limit


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


def _make_app_state(**settings_fields) -> SimpleNamespace:
    """Build a throwaway Starlette-like ``app.state`` for dependency-factory tests."""
    return SimpleNamespace(settings=SimpleNamespace(**settings_fields))


def _make_request_with_state(state: SimpleNamespace, host: str = "127.0.0.1") -> MagicMock:
    request = MagicMock()
    request.client.host = host
    request.app.state = state
    return request


class TestRateLimitFactory:
    """Tests for the ``rate_limit(name)`` FastAPI dependency factory."""

    def setup_method(self) -> None:
        # ``rate_limit`` memoises per name with lru_cache — clear between tests
        # so each test sees a fresh dependency callable.
        rate_limit.cache_clear()

    def test_returns_same_callable_for_same_name(self) -> None:
        """Repeated Depends(rate_limit("x")) declarations must share identity."""
        assert rate_limit("foo") is rate_limit("foo")

    def test_returns_distinct_callables_for_different_names(self) -> None:
        assert rate_limit("foo") is not rate_limit("bar")

    def test_reads_settings_by_name_and_lazily_creates_limiter(self) -> None:
        """First call pulls ``{name}_rate_limit`` / ``{name}_rate_window`` from settings."""
        state = _make_app_state(widget_rate_limit=2, widget_rate_window=60)
        dep = rate_limit("widget")

        dep(_make_request_with_state(state, host="10.0.0.1"))

        assert hasattr(state, "_widget_rate_limiter")
        limiter = state._widget_rate_limiter
        assert isinstance(limiter, RateLimiter)
        assert limiter.max_requests == 2
        assert limiter.window_seconds == 60

    def test_limiter_cached_on_app_state_between_requests(self) -> None:
        """Settings must be read only once; subsequent requests reuse the limiter."""
        state = _make_app_state(widget_rate_limit=5, widget_rate_window=60)
        dep = rate_limit("widget")

        dep(_make_request_with_state(state))
        limiter_first = state._widget_rate_limiter

        dep(_make_request_with_state(state))
        limiter_second = state._widget_rate_limiter

        assert limiter_first is limiter_second

    def test_enforces_configured_limit(self) -> None:
        """The factory-produced dependency enforces the configured window."""
        state = _make_app_state(widget_rate_limit=2, widget_rate_window=60)
        dep = rate_limit("widget")
        request = _make_request_with_state(state)

        for _ in range(2):
            dep(request)

        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_missing_settings_field_raises_attribute_error(self) -> None:
        """Typos in the name fail loudly instead of silently disabling the limit."""
        state = _make_app_state()  # no *_rate_limit / *_rate_window defined
        dep = rate_limit("nonexistent")

        with pytest.raises(AttributeError):
            dep(_make_request_with_state(state))

    def test_dependency_has_descriptive_name(self) -> None:
        """FastAPI docs / tracebacks should identify which limit fired."""
        dep = rate_limit("publish")
        assert dep.__name__ == "enforce_publish_rate_limit"

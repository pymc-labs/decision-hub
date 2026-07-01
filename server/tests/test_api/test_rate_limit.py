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


class TestMakeRateLimiterDep:
    """Unit tests for the make_rate_limiter_dep factory."""

    @staticmethod
    def _request_with_state(settings, host: str = "127.0.0.1") -> MagicMock:
        request = MagicMock()
        request.client.host = host
        request.app.state = SimpleNamespace(settings=settings)
        return request

    def test_lazily_instantiates_limiter_from_settings(self) -> None:
        """First call reads settings.{name}_rate_limit / _rate_window."""
        settings = SimpleNamespace(demo_rate_limit=2, demo_rate_window=60)
        dep = make_rate_limiter_dep("demo")
        request = self._request_with_state(settings)

        dep(request)  # should not raise
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_reuses_limiter_across_requests_on_same_app(self) -> None:
        """The limiter is cached on app.state and shared between calls."""
        settings = SimpleNamespace(demo_rate_limit=1, demo_rate_window=60)
        dep = make_rate_limiter_dep("demo")
        state = SimpleNamespace(settings=settings)

        req_a = MagicMock()
        req_a.client.host = "1.1.1.1"
        req_a.app.state = state

        req_b = MagicMock()
        req_b.client.host = "1.1.1.1"
        req_b.app.state = state

        dep(req_a)
        with pytest.raises(HTTPException):
            dep(req_b)  # second call from the same IP is blocked

    def test_different_names_have_isolated_counters(self) -> None:
        """Two named limiters on the same app do not share counters."""
        settings = SimpleNamespace(
            a_rate_limit=1,
            a_rate_window=60,
            b_rate_limit=1,
            b_rate_window=60,
        )
        state = SimpleNamespace(settings=settings)
        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.app.state = state

        dep_a = make_rate_limiter_dep("a")
        dep_b = make_rate_limiter_dep("b")

        dep_a(request)
        dep_b(request)  # b is independent; must not raise

        with pytest.raises(HTTPException):
            dep_a(request)

    def test_missing_setting_raises_attribute_error(self) -> None:
        """Typo in the name surfaces as AttributeError, not a silent no-op."""
        settings = SimpleNamespace()
        dep = make_rate_limiter_dep("missing")
        request = self._request_with_state(settings)
        with pytest.raises(AttributeError):
            dep(request)

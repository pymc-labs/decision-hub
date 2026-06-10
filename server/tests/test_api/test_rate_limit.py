"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, make_rate_limit_dependency


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


class TestMakeRateLimitDependency:
    """The factory builds the dependency closure used by every rate-limited route."""

    def _request_with_settings(self, **rate_settings: int) -> MagicMock:
        request = MagicMock()
        request.client.host = "10.0.0.1"
        request.app.state = MagicMock(spec=[])  # bare state, no cached limiter
        request.app.state.settings = MagicMock(**rate_settings)
        return request

    def test_lazy_initialises_limiter_on_first_call(self) -> None:
        dep = make_rate_limit_dependency("_demo_limiter", "demo_limit", "demo_window")
        request = self._request_with_settings(demo_limit=5, demo_window=60)

        assert not hasattr(request.app.state, "_demo_limiter")
        dep(request)

        limiter = request.app.state._demo_limiter
        assert isinstance(limiter, RateLimiter)
        assert limiter.max_requests == 5
        assert limiter.window_seconds == 60

    def test_reuses_cached_limiter_across_calls(self) -> None:
        dep = make_rate_limit_dependency("_demo_limiter", "demo_limit", "demo_window")
        request = self._request_with_settings(demo_limit=10, demo_window=60)

        dep(request)
        first = request.app.state._demo_limiter
        dep(request)
        assert request.app.state._demo_limiter is first

    def test_enforces_configured_limit(self) -> None:
        dep = make_rate_limit_dependency("_demo_limiter", "demo_limit", "demo_window")
        request = self._request_with_settings(demo_limit=2, demo_window=60)

        for _ in range(2):
            dep(request)

        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_different_attr_names_isolate_limiters(self) -> None:
        """Two factory instances on the same state are independent."""
        dep_a = make_rate_limit_dependency("_a_limiter", "a_limit", "a_window")
        dep_b = make_rate_limit_dependency("_b_limiter", "b_limit", "b_window")
        request = self._request_with_settings(a_limit=1, a_window=60, b_limit=5, b_window=60)

        dep_a(request)
        with pytest.raises(HTTPException):
            dep_a(request)

        # _b_limiter has plenty of budget left and uses its own bucket.
        for _ in range(5):
            dep_b(request)

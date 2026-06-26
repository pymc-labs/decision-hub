"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, enforce_rate_limit, get_or_create_limiter


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


class TestGetOrCreateLimiter:
    """Unit tests for the lazy limiter factory used on app.state."""

    def test_creates_limiter_on_first_call(self) -> None:
        state = SimpleNamespace()
        limiter = get_or_create_limiter(state, "search", max_requests=10, window_seconds=60)
        assert isinstance(limiter, RateLimiter)
        assert state._search_rate_limiter is limiter

    def test_returns_same_instance_on_subsequent_calls(self) -> None:
        state = SimpleNamespace()
        first = get_or_create_limiter(state, "search", max_requests=10, window_seconds=60)
        second = get_or_create_limiter(state, "search", max_requests=99, window_seconds=99)
        assert first is second  # cached: args after first call are ignored

    def test_different_names_get_independent_instances(self) -> None:
        state = SimpleNamespace()
        a = get_or_create_limiter(state, "auth", max_requests=5, window_seconds=60)
        b = get_or_create_limiter(state, "publish", max_requests=5, window_seconds=60)
        assert a is not b


class TestEnforceRateLimit:
    """The Depends-friendly dependency factory."""

    def _build_request(self, settings_dict: dict[str, int]) -> MagicMock:
        request = MagicMock()
        request.app.state = SimpleNamespace(settings=SimpleNamespace(**settings_dict))
        request.client.host = "127.0.0.1"
        return request

    def test_dependency_reads_settings_lazily(self) -> None:
        dep = enforce_rate_limit("publish", "publish_rate_limit", "publish_rate_window")
        request = self._build_request({"publish_rate_limit": 2, "publish_rate_window": 60})

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_dependency_caches_limiter_on_app_state(self) -> None:
        dep = enforce_rate_limit("search", "search_rate_limit", "search_rate_window")
        request = self._build_request({"search_rate_limit": 5, "search_rate_window": 60})

        dep(request)
        # The limiter should now live on app.state under the conventional name.
        assert isinstance(request.app.state._search_rate_limiter, RateLimiter)

    def test_dependency_name_reflects_limiter(self) -> None:
        dep = enforce_rate_limit("auth", "auth_rate_limit", "auth_rate_window")
        assert dep.__name__ == "enforce_auth_rate_limit"

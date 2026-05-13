"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter


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


class _State:
    """Stand-in for FastAPI's ``app.state`` (a plain attribute bag)."""


class TestRateLimitDepFactory:
    """Unit tests for the rate-limit dependency factory in registry_routes."""

    def test_factory_creates_limiter_lazily_and_caches_on_state(self) -> None:
        """The factory reads ``{name}_rate_limit`` / ``{name}_rate_window`` from
        settings and stores the limiter on ``app.state`` under
        ``_{name}_rate_limiter``, reusing it across requests.
        """
        from decision_hub.api.registry_routes import _make_rate_limit_dep

        settings = MagicMock()
        settings.list_skills_rate_limit = 2
        settings.list_skills_rate_window = 60
        state = _State()
        state.settings = settings

        request = MagicMock()
        request.app.state = state
        request.client.host = "1.2.3.4"

        dep = _make_rate_limit_dep("list_skills")
        dep(request)
        first = state._list_skills_rate_limiter
        dep(request)
        assert state._list_skills_rate_limiter is first

    def test_factory_enforces_configured_limit(self) -> None:
        """A dep built by the factory raises 429 once the configured cap is hit."""
        from decision_hub.api.registry_routes import _make_rate_limit_dep

        settings = MagicMock()
        settings.download_rate_limit = 2
        settings.download_rate_window = 60
        state = _State()
        state.settings = settings

        request = MagicMock()
        request.app.state = state
        request.client.host = "5.6.7.8"

        dep = _make_rate_limit_dep("download")
        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

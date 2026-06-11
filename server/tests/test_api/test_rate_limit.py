"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import (
    _RATE_LIMIT_NAMES,
    RateLimiter,
    install_rate_limiters,
    rate_limit_dep,
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


def _make_state_request(state) -> MagicMock:
    """Build a mock Request whose ``request.app.state`` points to *state*."""
    req = MagicMock()
    req.client.host = "127.0.0.1"
    req.app.state = state
    return req


class TestInstallRateLimiters:
    """The factory installs one limiter per registered name on app.state."""

    def test_installs_one_limiter_per_known_name(self) -> None:
        state = SimpleNamespace()
        settings = SimpleNamespace()
        for name in _RATE_LIMIT_NAMES:
            setattr(settings, f"{name}_rate_limit", 7)
            setattr(settings, f"{name}_rate_window", 11)

        install_rate_limiters(state, settings)

        for name in _RATE_LIMIT_NAMES:
            limiter = getattr(state, f"_{name}_rate_limiter")
            assert isinstance(limiter, RateLimiter)
            assert limiter.max_requests == 7
            assert limiter.window_seconds == 11

    def test_missing_setting_raises_attribute_error(self) -> None:
        """If a Settings field is missing, install_rate_limiters fails loudly."""
        state = SimpleNamespace()
        settings = SimpleNamespace()  # no fields at all
        with pytest.raises(AttributeError):
            install_rate_limiters(state, settings)


class TestRateLimitDep:
    """The factory-produced dependency reuses the pre-installed limiter."""

    def test_uses_preinstalled_limiter(self) -> None:
        # Manually install only the limiter under test (mirrors what
        # install_rate_limiters does for every name).
        state = SimpleNamespace()
        state._auth_rate_limiter = RateLimiter(max_requests=2, window_seconds=60)

        dep = rate_limit_dep("auth")
        request = _make_state_request(state)

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429
        # The dep MUST NOT have replaced the pre-installed limiter.
        assert state._auth_rate_limiter.max_requests == 2

    def test_lazy_fallback_when_not_installed(self) -> None:
        """If no limiter is installed (test app), the dep builds one from settings."""
        state = SimpleNamespace(settings=SimpleNamespace(search_rate_limit=1, search_rate_window=60))
        dep = rate_limit_dep("search")
        request = _make_state_request(state)

        dep(request)
        with pytest.raises(HTTPException):
            dep(request)
        # The lazily-created limiter is now attached so subsequent calls
        # don't rebuild it.
        assert isinstance(state._search_rate_limiter, RateLimiter)

    def test_dep_name_is_descriptive(self) -> None:
        dep = rate_limit_dep("publish")
        assert dep.__name__ == "rate_limit_publish"
        assert "publish" in (dep.__doc__ or "")

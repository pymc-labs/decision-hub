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


def _make_app_request(host: str = "127.0.0.1", **settings_overrides) -> MagicMock:
    """Create a mock Request with an app.state carrying a Settings stand-in.

    The `make_rate_limit_dep` factory reads `<name>_rate_limit` and
    `<name>_rate_window` attributes off `request.app.state.settings`, so the
    fake settings object only needs to expose those names.
    """
    request = MagicMock()
    request.client.host = host
    settings = SimpleNamespace(**settings_overrides)
    request.app.state = SimpleNamespace(settings=settings)
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


class TestMakeRateLimitDep:
    """Unit tests for the make_rate_limit_dep factory."""

    def test_lazy_initialises_limiter_from_settings(self) -> None:
        """First call should build a RateLimiter using <name>_rate_limit/window."""
        dep = make_rate_limit_dep("foo")
        request = _make_app_request(foo_rate_limit=2, foo_rate_window=60)

        assert getattr(request.app.state, "_foo_rate_limiter", None) is None
        dep(request)

        limiter = request.app.state._foo_rate_limiter
        assert isinstance(limiter, RateLimiter)
        assert limiter.max_requests == 2
        assert limiter.window_seconds == 60

    def test_caches_limiter_across_calls(self) -> None:
        """Subsequent calls must reuse the same limiter (state survives)."""
        dep = make_rate_limit_dep("bar")
        request = _make_app_request(bar_rate_limit=5, bar_rate_window=10)

        dep(request)
        first = request.app.state._bar_rate_limiter
        dep(request)
        second = request.app.state._bar_rate_limiter

        assert first is second

    def test_enforces_limit(self) -> None:
        """The factory's dependency must enforce the configured limit."""
        dep = make_rate_limit_dep("baz")
        request = _make_app_request(baz_rate_limit=2, baz_rate_window=60)

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_two_factories_use_separate_buckets(self) -> None:
        """Each name maps to its own state attribute; no cross-bucket leakage."""
        dep_a = make_rate_limit_dep("alpha")
        dep_b = make_rate_limit_dep("beta")
        request = _make_app_request(
            alpha_rate_limit=1,
            alpha_rate_window=60,
            beta_rate_limit=5,
            beta_rate_window=60,
        )

        dep_a(request)
        # alpha is now exhausted but beta should be unaffected
        with pytest.raises(HTTPException):
            dep_a(request)
        for _ in range(5):
            dep_b(request)

    def test_dep_has_stable_identity(self) -> None:
        """The returned callable's name should reflect the limiter group.

        FastAPI uses dependency-function identity for caching, so each name
        should produce a callable with a deterministic, debuggable __name__.
        """
        dep = make_rate_limit_dep("publish")
        assert dep.__name__ == "_enforce_publish_rate_limit"
        assert callable(dep)

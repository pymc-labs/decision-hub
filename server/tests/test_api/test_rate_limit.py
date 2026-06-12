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


# ---------------------------------------------------------------------------
# make_rate_limit_dep factory
# ---------------------------------------------------------------------------


def _make_request_with_app(host: str = "127.0.0.1", **settings_attrs) -> MagicMock:
    """Mock Request where `request.app.state` exposes settings + storage.

    The factory reads `<name>_rate_limit` / `<name>_rate_window` off
    `state.settings` and stashes the built limiter on `state._<name>_rate_limiter`.
    A `SimpleNamespace` lets us use getattr/setattr just like in production,
    instead of fighting MagicMock's auto-attribute creation.
    """
    request = MagicMock()
    request.client.host = host
    request.app.state = SimpleNamespace(settings=SimpleNamespace(**settings_attrs))
    return request


class TestMakeRateLimitDep:
    """Unit tests for the `make_rate_limit_dep` factory."""

    def test_lazy_initializes_limiter_from_settings(self) -> None:
        """First call reads <name>_rate_limit / <name>_rate_window and builds a RateLimiter."""
        dep = make_rate_limit_dep("publish")
        request = _make_request_with_app(publish_rate_limit=2, publish_rate_window=60)

        # Before any call the slot doesn't exist yet
        assert not hasattr(request.app.state, "_publish_rate_limiter")

        dep(request)

        limiter = request.app.state._publish_rate_limiter
        assert isinstance(limiter, RateLimiter)
        assert limiter.max_requests == 2
        assert limiter.window_seconds == 60

    def test_reuses_limiter_across_calls(self) -> None:
        """Repeated calls hit the same limiter instance, so the window persists."""
        dep = make_rate_limit_dep("publish")
        request = _make_request_with_app(publish_rate_limit=2, publish_rate_window=60)

        dep(request)
        first = request.app.state._publish_rate_limiter
        dep(request)
        second = request.app.state._publish_rate_limiter

        assert first is second

    def test_enforces_limit_after_factory_init(self) -> None:
        """The 3rd request when limit=2 hits the limiter and 429s."""
        dep = make_rate_limit_dep("search")
        request = _make_request_with_app(search_rate_limit=2, search_rate_window=60)

        dep(request)
        dep(request)

        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_different_names_get_independent_limiters(self) -> None:
        """Two factories for different names produce two limiters on app.state."""
        dep_a = make_rate_limit_dep("publish")
        dep_b = make_rate_limit_dep("search")
        request = _make_request_with_app(
            publish_rate_limit=1,
            publish_rate_window=60,
            search_rate_limit=5,
            search_rate_window=60,
        )

        dep_a(request)
        dep_b(request)

        assert request.app.state._publish_rate_limiter.max_requests == 1
        assert request.app.state._search_rate_limiter.max_requests == 5
        assert request.app.state._publish_rate_limiter is not request.app.state._search_rate_limiter

    def test_dependency_has_descriptive_name(self) -> None:
        """The returned callable carries an _enforce_<name>_rate_limit name for debug clarity."""
        dep = make_rate_limit_dep("scan_report")
        assert dep.__name__ == "_enforce_scan_report_rate_limit"
        assert dep.__qualname__ == "_enforce_scan_report_rate_limit"

    def test_missing_settings_field_raises_attribute_error(self) -> None:
        """A typo in the name surfaces as AttributeError, not silent zero-limit behaviour."""
        dep = make_rate_limit_dep("doesnotexist")
        request = _make_request_with_app()  # settings has no doesnotexist_rate_limit
        with pytest.raises(AttributeError):
            dep(request)

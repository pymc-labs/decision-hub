"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException

from decision_hub.api.rate_limit import RateLimiter, rate_limit_dep


def _make_request(host: str = "127.0.0.1", app: FastAPI | None = None) -> MagicMock:
    """Create a mock Request with a given client IP.

    When ``app`` is provided, the request's ``app.state`` points at the real
    FastAPI app so tests exercising ``rate_limit_dep`` share its registry.
    """
    request = MagicMock()
    request.client.host = host
    if app is not None:
        request.app = app
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

    def test_does_not_leak_empty_buckets_on_read(self) -> None:
        """Reading a rate limit for a new IP must not allocate a bucket
        that survives past the end of the request.

        The previous ``defaultdict``-based implementation inserted an
        empty list into ``_requests`` on every first request for a new
        IP, even if the request was immediately accepted — so the map
        grew by one entry per unique client between purges.  The new
        implementation stores only buckets that contain at least one
        live timestamp.
        """
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        limiter(_make_request("1.1.1.1"))
        assert list(limiter._requests.keys()) == ["1.1.1.1"]
        # Exactly one timestamp, not an empty list left behind
        assert len(limiter._requests["1.1.1.1"]) == 1

    def test_purge_bounds_memory_for_idle_ips(self) -> None:
        """After ``_PURGE_INTERVAL`` requests the limiter drops IPs whose
        last request has aged beyond the window — preventing unbounded
        growth from a rotating pool of short-lived clients."""
        limiter = RateLimiter(max_requests=100, window_seconds=10)
        limiter._PURGE_INTERVAL = 5  # shorten for test

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            # Five distinct IPs all hit once at t=1000 (one below _PURGE_INTERVAL)
            mock_time.monotonic.return_value = 1000.0
            for i in range(4):
                limiter(_make_request(f"10.0.0.{i}"))
            assert len(limiter._requests) == 4

            # Advance well past the window and trigger the purge on the next call
            mock_time.monotonic.return_value = 1100.0
            limiter(_make_request("10.0.0.99"))

            # Only the most recent IP should remain; the 4 stale ones were purged
            assert list(limiter._requests.keys()) == ["10.0.0.99"]


class TestRateLimitDep:
    """The ``rate_limit_dep`` factory replaces 9 near-identical closures."""

    def _make_app(self, *, max_requests: int, window_seconds: int) -> FastAPI:
        """Build a FastAPI app whose settings expose a ``search`` rate limit."""
        app = FastAPI()
        settings = MagicMock()
        settings.search_rate_limit = max_requests
        settings.search_rate_window = window_seconds
        app.state.settings = settings
        return app

    def test_lazy_initializes_limiter_on_first_call(self) -> None:
        """The limiter is constructed on first invocation, not at import time."""
        app = self._make_app(max_requests=3, window_seconds=60)
        dep = rate_limit_dep("search")

        assert not hasattr(app.state, "_rate_limiters")
        dep(_make_request("1.2.3.4", app=app))
        assert "search" in app.state._rate_limiters
        assert isinstance(app.state._rate_limiters["search"], RateLimiter)

    def test_reuses_same_limiter_across_calls(self) -> None:
        """Multiple calls share one bucket so counters actually accumulate."""
        app = self._make_app(max_requests=2, window_seconds=60)
        dep = rate_limit_dep("search")
        req = _make_request("1.2.3.4", app=app)

        dep(req)
        dep(req)
        with pytest.raises(HTTPException) as exc:
            dep(req)
        assert exc.value.status_code == 429

    def test_independent_limiters_for_different_names(self) -> None:
        """Two ``rate_limit_dep`` names must not share state even on the same app."""
        app = FastAPI()
        settings = MagicMock()
        settings.search_rate_limit = 1
        settings.search_rate_window = 60
        settings.publish_rate_limit = 1
        settings.publish_rate_window = 60
        app.state.settings = settings

        search_dep = rate_limit_dep("search")
        publish_dep = rate_limit_dep("publish")
        req = _make_request("9.9.9.9", app=app)

        search_dep(req)
        # Same IP consuming a different bucket is still allowed
        publish_dep(req)
        # But the search bucket is exhausted
        with pytest.raises(HTTPException):
            search_dep(req)

    def test_named_dep_shows_in_repr(self) -> None:
        """The generated dep's ``__name__`` includes the bucket name to aid tracing."""
        dep = rate_limit_dep("audit_log")
        assert dep.__name__ == "rate_limit_audit_log"

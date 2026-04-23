"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, rate_limit_dependency


def _make_request(host: str = "127.0.0.1", app_state: object | None = None) -> MagicMock:
    """Create a mock Request with a given client IP and optional app.state."""
    request = MagicMock()
    request.client.host = host
    if app_state is not None:
        request.app.state = app_state
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


class TestPurgeStaleEntries:
    """The purge counter must fire reliably even when concurrent calls would
    cause modulo-based triggers to be skipped."""

    def test_purge_removes_inactive_ips_after_threshold(self) -> None:
        """After _PURGE_EVERY calls, IPs with no recent timestamps are dropped."""
        # Use a 1-second window so stale entries are easy to construct.
        limiter = RateLimiter(max_requests=1000, window_seconds=1)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            # At t=1000, a bunch of one-shot clients hit the endpoint.
            mock_time.monotonic.return_value = 1000.0
            for i in range(50):
                limiter(_make_request(f"10.0.0.{i}"))

            # t jumps past the window; these IPs are now stale.
            mock_time.monotonic.return_value = 1005.0

            # A single other IP keeps hitting the endpoint.  After the
            # purge threshold is crossed, the 50 old IPs should be gone.
            active = _make_request("192.168.0.1")
            for _ in range(60):
                limiter(active)

            assert "192.168.0.1" in limiter._requests
            # All 50 stale IPs should have been purged.
            stale_keys = [k for k in limiter._requests if k.startswith("10.0.0.")]
            assert stale_keys == []

    def test_purge_counter_resets_after_firing(self) -> None:
        """The internal call counter resets so purge fires periodically."""
        limiter = RateLimiter(max_requests=1000, window_seconds=60)

        with patch("decision_hub.api.rate_limit._PURGE_EVERY", 5):
            request = _make_request()
            for _ in range(5):
                limiter(request)
            # After exactly _PURGE_EVERY calls, counter must reset to 0.
            assert limiter._calls == 0


class TestRateLimitDependency:
    """The factory returns a FastAPI dependency that caches one limiter per state."""

    def test_creates_limiter_lazily_and_caches(self) -> None:
        dep = rate_limit_dependency("search")

        settings = SimpleNamespace(search_rate_limit=2, search_rate_window=60)
        state = SimpleNamespace(settings=settings)
        request = _make_request(app_state=state)

        dep(request)
        dep(request)

        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

        # The limiter is attached to state and reused on subsequent calls.
        limiter = state._search_rate_limiter
        assert isinstance(limiter, RateLimiter)
        assert limiter.max_requests == 2
        assert limiter.window_seconds == 60

    def test_independent_names_do_not_share_limiters(self) -> None:
        dep_a = rate_limit_dependency("search")
        dep_b = rate_limit_dependency("publish")

        settings = SimpleNamespace(
            search_rate_limit=1,
            search_rate_window=60,
            publish_rate_limit=1,
            publish_rate_window=60,
        )
        state = SimpleNamespace(settings=settings)
        request = _make_request(app_state=state)

        dep_a(request)
        # Exhausting the search limiter must not affect publish.
        dep_b(request)

        with pytest.raises(HTTPException):
            dep_a(request)
        with pytest.raises(HTTPException):
            dep_b(request)

    def test_dependency_exposes_descriptive_name(self) -> None:
        dep = rate_limit_dependency("audit_log")
        assert dep.__name__ == "enforce_audit_log_rate_limit"

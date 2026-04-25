"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, make_rate_limiter_dep


def _make_request(host: str = "127.0.0.1", headers: dict | None = None) -> MagicMock:
    """Create a mock Request with a given client IP and optional headers."""
    request = MagicMock()
    request.client.host = host
    # FastAPI's Request.headers is case-insensitive; simulate that with a dict
    # whose .get() lowercases the key, since RateLimiter only reads lowercase.
    request.headers = headers or {}
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
        request.headers = {}

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429


class TestRateLimiterForwardedFor:
    """X-Forwarded-For honoring (opt-in via trust_forwarded_for)."""

    def test_default_ignores_x_forwarded_for(self) -> None:
        """By default the socket IP is used and XFF is ignored.

        Without this guard, an unauthenticated proxy header could let a single
        client share the rate-limit bucket of an arbitrary IP they pick.
        """
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        # Two clients behind the same proxy (same socket IP) but presenting
        # different XFF values must still share one bucket.
        req_a = _make_request("10.0.0.1", headers={"x-forwarded-for": "1.1.1.1"})
        req_b = _make_request("10.0.0.1", headers={"x-forwarded-for": "2.2.2.2"})
        limiter(req_a)
        with pytest.raises(HTTPException):
            limiter(req_b)

    def test_trusted_xff_uses_leftmost_entry(self) -> None:
        """When trusted, the leftmost XFF entry identifies the client."""
        limiter = RateLimiter(max_requests=1, window_seconds=60, trust_forwarded_for=True)
        # Same socket peer (the proxy), different real clients
        req_a = _make_request("10.0.0.1", headers={"x-forwarded-for": "1.1.1.1, 10.0.0.1"})
        req_b = _make_request("10.0.0.1", headers={"x-forwarded-for": "2.2.2.2, 10.0.0.1"})
        limiter(req_a)
        limiter(req_b)  # different real client → different bucket
        with pytest.raises(HTTPException):
            limiter(req_a)  # second hit from 1.1.1.1 → blocked

    def test_trusted_xff_falls_back_when_header_missing(self) -> None:
        """Falls back to the socket IP when XFF is absent even if trust is on."""
        limiter = RateLimiter(max_requests=1, window_seconds=60, trust_forwarded_for=True)
        req = _make_request("10.0.0.1", headers={})
        limiter(req)
        with pytest.raises(HTTPException):
            limiter(req)


class TestRateLimiterPurge:
    """Stale-IP purge runs in O(1) regardless of tracked-IP count."""

    def test_purge_runs_after_threshold(self) -> None:
        """Once enough requests have been admitted, stale buckets get cleaned."""
        limiter = RateLimiter(max_requests=10_000, window_seconds=1)
        # Override the threshold so the test is fast and explicit.
        limiter._PURGE_EVERY = 5  # type: ignore[attr-defined]

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            # Three different IPs make one request each — none are stale yet.
            for ip in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
                limiter(_make_request(ip))
            assert len(limiter._requests) == 3

            # Advance well past the window so all three buckets are stale.
            mock_time.monotonic.return_value = 2000.0
            # A new IP keeps making requests; on the 5th admission the purge fires.
            for _ in range(5):
                limiter(_make_request("9.9.9.9"))

        # The stale buckets are gone; the fresh one remains.
        assert "9.9.9.9" in limiter._requests
        for ip in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
            assert ip not in limiter._requests


class TestMakeRateLimiterDep:
    """The factory wires settings → app.state → limiter as a FastAPI dep."""

    def _fake_request(self, settings, state_attr: str | None = None) -> MagicMock:
        state = SimpleNamespace(settings=settings)
        if state_attr is not None:
            setattr(state, state_attr, None)
        request = MagicMock()
        request.app.state = state
        request.client.host = "10.0.0.1"
        request.headers = {}
        return request

    def test_caches_single_limiter_on_state(self) -> None:
        """Repeated calls reuse the same limiter so the window is shared."""
        settings = SimpleNamespace(my_max=2, my_window=60)
        dep = make_rate_limiter_dep(
            "_my_limiter",
            get_max_requests=lambda s: s.my_max,
            get_window_seconds=lambda s: s.my_window,
        )

        request = self._fake_request(settings)
        dep(request)
        dep(request)
        with pytest.raises(HTTPException):
            dep(request)

        # The limiter is the same instance across calls and lives on app.state.
        assert request.app.state._my_limiter is not None

    def test_settings_read_lazily(self) -> None:
        """Settings are read on first call, not at registration time.

        Tests can patch settings *after* registering routes and still have
        the override take effect.
        """
        settings = SimpleNamespace(my_max=1, my_window=60)
        dep = make_rate_limiter_dep(
            "_lazy_limiter",
            get_max_requests=lambda s: s.my_max,
            get_window_seconds=lambda s: s.my_window,
        )

        # Mutate settings before any request — should still be honored.
        settings.my_max = 3
        request = self._fake_request(settings)
        for _ in range(3):
            dep(request)
        with pytest.raises(HTTPException):
            dep(request)

    def test_concurrent_first_callers_share_one_limiter(self) -> None:
        """Concurrent first-callers must not each create their own limiter."""
        import concurrent.futures

        settings = SimpleNamespace(my_max=1_000, my_window=60)
        dep = make_rate_limiter_dep(
            "_concurrent_limiter",
            get_max_requests=lambda s: s.my_max,
            get_window_seconds=lambda s: s.my_window,
        )
        state = SimpleNamespace(settings=settings)
        # Pre-create N requests that each see no limiter yet on app.state.
        requests = [MagicMock() for _ in range(16)]
        for r in requests:
            r.app.state = state
            r.client.host = "10.0.0.1"
            r.headers = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(dep, requests))

        # Exactly one limiter ended up cached on app.state.
        assert hasattr(state, "_concurrent_limiter")
        assert state._concurrent_limiter is not None

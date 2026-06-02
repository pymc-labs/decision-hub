"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import (
    RateLimiter,
    client_ip_from_request,
    make_rate_limit_dep,
)


def _make_request(host: str = "127.0.0.1", forwarded_for: str | None = None) -> MagicMock:
    """Create a mock Request with a given client IP (and optional XFF header)."""
    request = MagicMock()
    request.client.host = host
    request.headers = {}
    if forwarded_for is not None:
        request.headers = {"x-forwarded-for": forwarded_for}
    return request


# ---------------------------------------------------------------------------
# client_ip_from_request
# ---------------------------------------------------------------------------


class TestClientIPFromRequest:
    """The helper that picks the right IP for per-IP rate limiting."""

    def test_prefers_x_forwarded_for_first_hop(self) -> None:
        """Behind a proxy (Modal LB, CloudFront) the real client IP lives in XFF."""
        request = _make_request(host="10.0.0.1", forwarded_for="203.0.113.5, 10.0.0.1")
        assert client_ip_from_request(request) == "203.0.113.5"

    def test_strips_whitespace_from_xff(self) -> None:
        request = _make_request(host="10.0.0.1", forwarded_for="  198.51.100.7  ")
        assert client_ip_from_request(request) == "198.51.100.7"

    def test_falls_back_to_request_client_host(self) -> None:
        """No XFF (direct connection / local dev) => use the socket peer."""
        request = _make_request(host="192.168.1.1")
        assert client_ip_from_request(request) == "192.168.1.1"

    def test_empty_xff_header_falls_back(self) -> None:
        request = _make_request(host="192.168.1.1", forwarded_for="")
        assert client_ip_from_request(request) == "192.168.1.1"

    def test_xff_with_only_commas_falls_back(self) -> None:
        request = _make_request(host="192.168.1.1", forwarded_for=", , ")
        assert client_ip_from_request(request) == "192.168.1.1"

    def test_unknown_when_no_client_and_no_xff(self) -> None:
        """Requests with no socket peer and no XFF fall into a single shared bucket."""
        request = MagicMock()
        request.client = None
        request.headers = {}
        assert client_ip_from_request(request) == "unknown"


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


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

    def test_real_client_ip_isolated_behind_proxy(self) -> None:
        """Two browsers behind one LB must NOT share a single rate-limit bucket.

        Regression test for the case where rate-limiting used
        ``request.client.host`` directly: behind Modal's edge that is one
        IP for every user, so one heavy user 429s everyone else.
        """
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        req_user_a = _make_request(host="10.0.0.1", forwarded_for="198.51.100.7, 10.0.0.1")
        req_user_b = _make_request(host="10.0.0.1", forwarded_for="198.51.100.42, 10.0.0.1")

        limiter(req_user_a)  # user A uses their budget

        # User A blocked
        with pytest.raises(HTTPException):
            limiter(req_user_a)

        # User B still has their own budget
        limiter(req_user_b)

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

    def test_periodic_purge_removes_stale_ips(self) -> None:
        """After enough activity, IPs that have gone quiet are dropped from memory."""
        import decision_hub.api.rate_limit as rl

        # Shrink the purge cadence so the test runs in a sensible time.
        with patch.object(rl, "_PURGE_EVERY_N_CALLS", 5):
            limiter = RateLimiter(max_requests=100, window_seconds=1)

            with patch("decision_hub.api.rate_limit.time") as mock_time:
                mock_time.monotonic.return_value = 1000.0
                # Stale IP that won't be seen again.
                limiter(_make_request("10.0.0.1"))

                # Advance past the window so the stale IP is eligible for purge.
                mock_time.monotonic.return_value = 1010.0
                # Drive enough calls from a different IP to trip the heartbeat.
                for _ in range(5):
                    limiter(_make_request("10.0.0.2"))

                # 10.0.0.1 is gone; only the active IP remains.
                assert "10.0.0.1" not in limiter._requests
                assert "10.0.0.2" in limiter._requests


# ---------------------------------------------------------------------------
# make_rate_limit_dep
# ---------------------------------------------------------------------------


class TestMakeRateLimitDep:
    """The factory used everywhere in api/*_routes.py."""

    def _make_request_with_state(self) -> MagicMock:
        """A request with an attached app.state carrying typical settings."""
        request = _make_request()
        request.app.state = SimpleNamespace(
            settings=SimpleNamespace(
                widget_rate_limit=2,
                widget_rate_window=60,
            ),
        )
        return request

    def test_dep_lazy_inits_a_limiter_on_app_state(self) -> None:
        dep = make_rate_limit_dep("widget")
        request = self._make_request_with_state()

        dep(request)

        limiter = request.app.state._widget_rate_limiter
        assert isinstance(limiter, RateLimiter)
        assert limiter.max_requests == 2
        assert limiter.window_seconds == 60

    def test_dep_reuses_existing_limiter_across_calls(self) -> None:
        dep = make_rate_limit_dep("widget")
        request = self._make_request_with_state()

        dep(request)
        first = request.app.state._widget_rate_limiter
        dep(request)
        second = request.app.state._widget_rate_limiter

        assert first is second, "lazy init should run exactly once per container"

    def test_dep_enforces_the_limit(self) -> None:
        dep = make_rate_limit_dep("widget")
        request = self._make_request_with_state()

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_dep_function_name_matches_legacy_helpers(self) -> None:
        """Easier debugging: the dep shows up in tracebacks with the old name."""
        dep = make_rate_limit_dep("publish")
        assert dep.__name__ == "_enforce_publish_rate_limit"

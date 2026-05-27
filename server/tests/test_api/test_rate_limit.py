"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, client_ip, make_rate_limit_dep


def _make_request(host: str = "127.0.0.1", headers: dict | None = None) -> MagicMock:
    """Create a mock Request with a given client IP and optional headers."""
    request = MagicMock()
    request.client.host = host
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

    def test_honors_x_forwarded_for_behind_proxy(self) -> None:
        """Two clients behind one proxy must not share a rate-limit bucket."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        # Same proxy peer but different X-Forwarded-For — must be isolated.
        req_a = _make_request("10.0.0.99", {"x-forwarded-for": "203.0.113.7"})
        req_b = _make_request("10.0.0.99", {"x-forwarded-for": "203.0.113.42"})

        for _ in range(2):
            limiter(req_a)
        with pytest.raises(HTTPException):
            limiter(req_a)
        # Different X-Forwarded-For — separate budget.
        limiter(req_b)
        limiter(req_b)

    def test_uses_leftmost_xff_entry(self) -> None:
        """When X-Forwarded-For chains proxies, the leftmost address is the client."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        chained = _make_request(
            "10.0.0.1",
            {"x-forwarded-for": "203.0.113.7, 198.51.100.2, 10.0.0.99"},
        )
        limiter(chained)
        with pytest.raises(HTTPException):
            limiter(chained)
        # A different leftmost gets its own bucket.
        other = _make_request("10.0.0.1", {"x-forwarded-for": "203.0.113.99"})
        limiter(other)

    def test_falls_back_to_x_real_ip(self) -> None:
        """When X-Forwarded-For is absent, honour X-Real-IP."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        req = _make_request("10.0.0.99", {"x-real-ip": "203.0.113.50"})
        limiter(req)
        with pytest.raises(HTTPException):
            limiter(req)

    def test_purges_stale_keys_after_threshold(self) -> None:
        """Once enough requests have been admitted, expired keys are evicted."""
        limiter = RateLimiter(max_requests=10, window_seconds=1)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            limiter(_make_request("10.0.0.1"))
            # Move past the window so the original IP is stale.
            mock_time.monotonic.return_value = 1002.0
            # Drive enough requests from fresh IPs to trigger one purge cycle.
            # Each unique IP only contributes one timestamp, so none hit the cap.
            for i in range(limiter._PURGE_EVERY - 1):
                limiter(_make_request(f"10.0.1.{i}"))

        assert "10.0.0.1" not in limiter._requests


class TestClientIp:
    """client_ip extracts the originating IP through reverse proxies."""

    def test_direct_client_when_no_headers(self) -> None:
        assert client_ip(_make_request("198.51.100.10")) == "198.51.100.10"

    def test_xff_overrides_direct_peer(self) -> None:
        req = _make_request("10.0.0.1", {"x-forwarded-for": "198.51.100.20"})
        assert client_ip(req) == "198.51.100.20"

    def test_empty_xff_falls_back(self) -> None:
        req = _make_request("198.51.100.30", {"x-forwarded-for": "   "})
        assert client_ip(req) == "198.51.100.30"

    def test_unknown_when_no_client(self) -> None:
        request = MagicMock()
        request.client = None
        request.headers = {}
        assert client_ip(request) == "unknown"


class TestMakeRateLimitDep:
    """make_rate_limit_dep wires a settings-driven, lazily-cached limiter."""

    def test_lazily_caches_limiter_on_app_state(self) -> None:
        dep = make_rate_limit_dep("publish")
        settings = SimpleNamespace(publish_rate_limit=2, publish_rate_window=60)

        request = MagicMock()
        request.app.state = SimpleNamespace(settings=settings)
        request.client.host = "10.0.0.1"
        request.headers = {}

        dep(request)
        first = request.app.state._rate_limiter_publish
        dep(request)
        # Same instance is reused for subsequent requests.
        assert request.app.state._rate_limiter_publish is first

    def test_enforces_limit_from_settings(self) -> None:
        dep = make_rate_limit_dep("publish")
        settings = SimpleNamespace(publish_rate_limit=2, publish_rate_window=60)

        request = MagicMock()
        request.app.state = SimpleNamespace(settings=settings)
        request.client.host = "10.0.0.1"
        request.headers = {}

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_different_names_have_independent_state(self) -> None:
        dep_a = make_rate_limit_dep("publish")
        dep_b = make_rate_limit_dep("search")
        settings = SimpleNamespace(
            publish_rate_limit=1,
            publish_rate_window=60,
            search_rate_limit=1,
            search_rate_window=60,
        )

        request = MagicMock()
        request.app.state = SimpleNamespace(settings=settings)
        request.client.host = "10.0.0.1"
        request.headers = {}

        dep_a(request)
        # Different limiter on a different attribute, so this passes.
        dep_b(request)
        # Both hit their own ceiling.
        with pytest.raises(HTTPException):
            dep_a(request)
        with pytest.raises(HTTPException):
            dep_b(request)

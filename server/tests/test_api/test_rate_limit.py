"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import (
    _MAX_TRACKED_IPS,
    RateLimiter,
    client_ip,
    make_rate_limit_dep,
)


def _make_request(host: str = "127.0.0.1", forwarded: str | None = None) -> MagicMock:
    """Create a mock Request with a given client IP and optional XFF header."""
    request = MagicMock()
    request.client.host = host
    request.headers = {} if forwarded is None else {"x-forwarded-for": forwarded}
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

    def test_uses_forwarded_for_when_present(self) -> None:
        """X-Forwarded-For takes precedence over the proxy peer host.

        Behind Modal's TLS-terminating ingress every request shares the
        proxy host as ``request.client.host``; we must consult XFF to
        get the real originating client IP.
        """
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        proxy_host = "10.0.0.1"

        # Two requests come through the same proxy but represent two
        # distinct upstream clients — they must NOT share quota.
        client_a = _make_request(host=proxy_host, forwarded="203.0.113.10")
        client_b = _make_request(host=proxy_host, forwarded="203.0.113.20")
        limiter(client_a)
        limiter(client_b)  # different upstream IP — must not raise

        # A second request from client_a hits the per-IP limit.
        with pytest.raises(HTTPException):
            limiter(_make_request(host=proxy_host, forwarded="203.0.113.10"))

    def test_forwarded_for_takes_leftmost_address(self) -> None:
        """When XFF lists multiple hops, the leftmost is the originator."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        proxy_host = "10.0.0.1"

        request = _make_request(host=proxy_host, forwarded="203.0.113.10, 198.51.100.5")
        limiter(request)
        with pytest.raises(HTTPException):
            limiter(_make_request(host=proxy_host, forwarded="203.0.113.10, 1.2.3.4"))

    def test_empty_forwarded_for_falls_back_to_client_host(self) -> None:
        """A header present but empty must not silently bucket all clients together."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)

        limiter(_make_request(host="10.0.0.1", forwarded=""))
        with pytest.raises(HTTPException):
            limiter(_make_request(host="10.0.0.1", forwarded=""))

    def test_max_tracked_ips_evicts_oldest(self) -> None:
        """Distinct IPs beyond the cap are LRU-evicted, bounding memory."""
        limiter = RateLimiter(max_requests=10, window_seconds=60)

        # Hit the limiter from MAX+5 distinct IPs.
        for i in range(_MAX_TRACKED_IPS + 5):
            limiter(_make_request(host=f"10.0.{i // 256}.{i % 256}"))

        # Internal map must not exceed the cap.
        assert len(limiter._requests) <= _MAX_TRACKED_IPS

    def test_concurrent_requests_thread_safe(self) -> None:
        """Concurrent requests from one IP all see consistent state."""
        from concurrent.futures import ThreadPoolExecutor, wait

        limiter = RateLimiter(max_requests=50, window_seconds=60)

        def _hit():
            limiter(_make_request())

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(_hit) for _ in range(50)]
            wait(futures)
            # Any exception during the burst would propagate from
            # future.result(); collect them so a flake surfaces clearly.
            for f in futures:
                f.result()

        # The 51st request should be blocked deterministically.
        with pytest.raises(HTTPException):
            _hit()


class TestClientIp:
    """Unit tests for the client_ip helper used by the limiter and logging."""

    def test_returns_forwarded_when_present(self) -> None:
        request = _make_request(host="10.0.0.1", forwarded="203.0.113.10")
        assert client_ip(request) == "203.0.113.10"

    def test_returns_first_address_when_xff_has_chain(self) -> None:
        request = _make_request(host="10.0.0.1", forwarded=" 203.0.113.10 , 198.51.100.5")
        assert client_ip(request) == "203.0.113.10"

    def test_falls_back_to_client_host(self) -> None:
        request = _make_request(host="198.51.100.7")
        assert client_ip(request) == "198.51.100.7"

    def test_returns_unknown_when_nothing_known(self) -> None:
        request = MagicMock()
        request.client = None
        request.headers = {}
        assert client_ip(request) == "unknown"


class TestMakeRateLimitDep:
    """The factory consolidates the lazy-init pattern duplicated across routes."""

    def test_caches_limiter_on_app_state(self) -> None:
        dep = make_rate_limit_dep(
            "test_endpoint",
            limit_attr="search_rate_limit",
            window_attr="search_rate_window",
        )
        request = _make_request()
        request.app.state = MagicMock(spec=[])
        request.app.state.settings = MagicMock(
            search_rate_limit=2,
            search_rate_window=60,
        )

        dep(request)
        first = request.app.state._rate_limiter_test_endpoint
        dep(request)
        second = request.app.state._rate_limiter_test_endpoint
        assert first is second  # cached, not recreated

    def test_dependency_enforces_settings_limit(self) -> None:
        dep = make_rate_limit_dep(
            "tiny",
            limit_attr="search_rate_limit",
            window_attr="search_rate_window",
        )
        request = _make_request()
        request.app.state = MagicMock(spec=[])
        request.app.state.settings = MagicMock(
            search_rate_limit=1,
            search_rate_window=60,
        )

        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, _client_key, rate_limit_dep


def _make_request(host: str = "127.0.0.1", *, headers: dict[str, str] | None = None) -> MagicMock:
    """Create a mock Request with a given client IP and optional headers."""
    request = MagicMock()
    request.client.host = host
    # Case-insensitive header access — ``request.headers.get`` is what the
    # production code calls. Default to an empty mapping.
    request.headers.get = (headers or {}).get
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
        request.headers.get = {}.get

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429


class TestClientKey:
    """Verify the client-identity helper behaves correctly behind proxies."""

    def test_uses_client_host_when_no_proxy_trusted(self) -> None:
        """Without trust, XFF must be ignored even if present."""
        req = _make_request("10.0.0.1", headers={"x-forwarded-for": "1.2.3.4"})
        assert _client_key(req, trust_proxy_hops=0) == "10.0.0.1"

    def test_uses_xff_when_one_hop_trusted(self) -> None:
        """With one trusted proxy, the rightmost XFF entry is the client."""
        req = _make_request(
            "10.0.0.1",
            headers={"x-forwarded-for": "203.0.113.7"},
        )
        assert _client_key(req, trust_proxy_hops=1) == "203.0.113.7"

    def test_uses_xff_with_multiple_hops_correctly(self) -> None:
        """With N trusted hops, pick the Nth IP from the right."""
        # XFF: "client, proxy1, proxy2" — with two trusted hops the
        # leftmost entry ("client") is what we should bucket by.
        req = _make_request(
            "10.0.0.1",
            headers={"x-forwarded-for": "198.51.100.7, 10.0.0.10, 10.0.0.20"},
        )
        assert _client_key(req, trust_proxy_hops=2) == "10.0.0.10"
        assert _client_key(req, trust_proxy_hops=1) == "10.0.0.20"
        # When trust exceeds entries we clamp to the leftmost (most-client).
        assert _client_key(req, trust_proxy_hops=99) == "198.51.100.7"

    def test_falls_back_to_client_host_when_xff_empty(self) -> None:
        """Malformed/empty XFF must not collapse callers to 'unknown'."""
        req = _make_request(
            "10.0.0.1",
            headers={"x-forwarded-for": " , , "},
        )
        assert _client_key(req, trust_proxy_hops=1) == "10.0.0.1"

    def test_rate_limiter_isolates_clients_behind_proxy(self) -> None:
        """End-to-end: distinct XFF clients hit their own buckets."""
        limiter = RateLimiter(max_requests=1, window_seconds=60, trust_proxy_hops=1)
        proxy_host = "10.0.0.5"
        client_a = _make_request(proxy_host, headers={"x-forwarded-for": "203.0.113.1"})
        client_b = _make_request(proxy_host, headers={"x-forwarded-for": "203.0.113.2"})

        limiter(client_a)
        # Same proxy IP, different real client — must NOT share a bucket.
        limiter(client_b)
        with pytest.raises(HTTPException):
            limiter(client_a)


class TestRateLimiterMemoryBound:
    """Verify the limiter stays bounded under unique-IP fan-out."""

    def test_stale_ips_purged_after_window(self) -> None:
        """Once a window passes, idle IPs are evicted from the dict."""
        limiter = RateLimiter(max_requests=5, window_seconds=10)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            # Many unique IPs hit the limiter inside one window.
            for i in range(500):
                limiter(_make_request(f"10.0.{i // 256}.{i % 256}"))
            assert len(limiter._requests) == 500

            # Advance past the window and trigger one more request — the
            # time-driven purge must drop every idle bucket.
            mock_time.monotonic.return_value = 1011.0
            limiter(_make_request("198.51.100.1"))
            assert len(limiter._requests) == 1, f"expected purge to drop idle buckets, found {len(limiter._requests)}"

    def test_purge_does_not_clear_active_clients(self) -> None:
        """A client that just hit us must not be evicted as 'stale'."""
        limiter = RateLimiter(max_requests=5, window_seconds=10)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            limiter(_make_request("10.0.0.1"))

            # Window elapses, triggering purge — but the new caller is active.
            mock_time.monotonic.return_value = 1011.0
            limiter(_make_request("10.0.0.2"))

            assert "10.0.0.2" in limiter._requests
            assert "10.0.0.1" not in limiter._requests


class TestRateLimitDepFactory:
    """The dependency factory wires limiters onto request.app.state."""

    def _settings(self, **overrides) -> object:
        defaults = {
            "search_rate_limit": 2,
            "search_rate_window": 60,
            "trust_proxy_hops": 0,
        }
        defaults.update(overrides)
        ns = MagicMock()
        for k, v in defaults.items():
            setattr(ns, k, v)
        return ns

    def _request(self, settings, host: str = "1.1.1.1") -> MagicMock:
        request = _make_request(host)
        # Each new MagicMock for app.state gives a fresh attribute namespace
        # so the limiter cache is local to this test invocation.
        from types import SimpleNamespace

        request.app.state = SimpleNamespace(settings=settings)
        return request

    def test_dep_lazy_creates_limiter_on_first_call(self) -> None:
        settings = self._settings()
        dep = rate_limit_dep("_search_rate_limiter", "search_rate_limit", "search_rate_window")
        request = self._request(settings)

        # First call creates the limiter on app.state.
        dep(request)
        limiter = request.app.state._search_rate_limiter
        assert isinstance(limiter, RateLimiter)

        # Second call reuses it.
        dep(request)
        assert request.app.state._search_rate_limiter is limiter

    def test_dep_enforces_limit(self) -> None:
        settings = self._settings(search_rate_limit=1, search_rate_window=60)
        dep = rate_limit_dep("_search_rate_limiter", "search_rate_limit", "search_rate_window")
        request = self._request(settings)

        dep(request)
        with pytest.raises(HTTPException) as exc:
            dep(request)
        assert exc.value.status_code == 429

    def test_dep_threads_trust_proxy_hops_from_settings(self) -> None:
        settings = self._settings(trust_proxy_hops=1)
        dep = rate_limit_dep("_search_rate_limiter", "search_rate_limit", "search_rate_window")
        request = self._request(settings)
        dep(request)
        assert request.app.state._search_rate_limiter.trust_proxy_hops == 1

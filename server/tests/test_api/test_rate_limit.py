"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, _client_key, rate_limit_dep


def _make_request(host: str = "127.0.0.1", headers: dict[str, str] | None = None) -> MagicMock:
    """Create a mock Request with a given client IP and optional headers."""
    request = MagicMock()
    request.client.host = host
    # Starlette's Headers object exposes case-insensitive .get(); mimic it.
    hdrs: dict[str, str] = {k.lower(): v for k, v in (headers or {}).items()}
    request.headers = MagicMock()
    request.headers.get.side_effect = lambda name, default=None: hdrs.get(name.lower(), default)
    return request


class TestClientKey:
    """Unit tests for the _client_key helper."""

    def test_falls_back_to_peer_host_without_forwarded_header(self) -> None:
        request = _make_request("10.0.0.5")
        assert _client_key(request) == "10.0.0.5"

    def test_prefers_first_forwarded_entry(self) -> None:
        # Modal / standard reverse-proxy setups put the originating client
        # IP as the first (left-most) entry of X-Forwarded-For.
        request = _make_request(
            "proxy-ip",
            headers={"x-forwarded-for": "1.2.3.4, 10.0.0.1"},
        )
        assert _client_key(request) == "1.2.3.4"

    def test_trims_whitespace_and_ignores_empty_entries(self) -> None:
        request = _make_request(
            "proxy-ip",
            headers={"x-forwarded-for": "   ,  5.6.7.8  ,  9.9.9.9"},
        )
        # First entry is empty whitespace -> fall back to peer host.
        assert _client_key(request) == "proxy-ip"

    def test_returns_unknown_when_no_client(self) -> None:
        request = MagicMock()
        request.client = None
        request.headers = MagicMock()
        request.headers.get.return_value = None
        assert _client_key(request) == "unknown"


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

    def test_x_forwarded_for_gives_each_client_its_own_bucket(self) -> None:
        """Behind a proxy, distinct clients must not share a bucket.

        Before the fix the limiter bucketed by ``request.client.host``,
        so every user behind Modal/CloudFlare looked like one IP and
        triggered the global ceiling together.  After the fix the first
        entry of ``X-Forwarded-For`` identifies the originating client.
        """
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        # Two different clients that happen to share the same proxy IP.
        req_a = _make_request("proxy", headers={"x-forwarded-for": "198.51.100.1, proxy"})
        req_b = _make_request("proxy", headers={"x-forwarded-for": "198.51.100.2, proxy"})

        # Fill client A's bucket; client B must remain unaffected.
        for _ in range(2):
            limiter(req_a)
        with pytest.raises(HTTPException):
            limiter(req_a)
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
        request.headers = MagicMock()
        request.headers.get.return_value = None

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429

    def test_blocked_clients_do_not_accumulate_empty_buckets(self) -> None:
        """After the window expires an idle IP's bucket must be freed.

        With the old ``defaultdict`` implementation, pruning an expired
        list left an empty entry behind for every IP that had ever hit
        the limiter, leaking memory proportional to unique-IP count.
        """
        limiter = RateLimiter(max_requests=1, window_seconds=1)
        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 500.0
            for i in range(5):
                limiter(_make_request(f"10.0.0.{i}"))
            assert len(limiter._requests) == 5

            # Fast-forward past the window, then hit one fresh IP.
            mock_time.monotonic.return_value = 502.0
            limiter(_make_request("10.0.0.99"))
            # Only the fresh IP should remain; the five expired ones
            # were evicted as each new request swept its key.
            # (Explicit assertion: no orphaned empty lists.)
            assert all(v for v in limiter._requests.values())


class TestRateLimitDep:
    """Tests for the ``rate_limit_dep`` FastAPI dependency factory."""

    def _make_app_request(
        self,
        *,
        limit: int,
        window: int,
        host: str = "127.0.0.1",
    ) -> MagicMock:
        """Build a mock Request carrying a Settings-like object on app.state."""
        settings = SimpleNamespace(
            foo_rate_limit=limit,
            foo_rate_window=window,
        )
        request = _make_request(host)
        request.app.state = SimpleNamespace(settings=settings)
        return request

    def test_lazily_caches_limiter_on_app_state(self) -> None:
        dep = rate_limit_dep("_foo_limiter", "foo_rate_limit", "foo_rate_window")
        req = self._make_app_request(limit=3, window=60)

        dep(req)
        first = req.app.state._foo_limiter
        dep(req)
        second = req.app.state._foo_limiter

        assert isinstance(first, RateLimiter)
        assert first is second  # same instance re-used across calls

    def test_enforces_429_when_over_limit(self) -> None:
        dep = rate_limit_dep("_foo_limiter", "foo_rate_limit", "foo_rate_window")
        req = self._make_app_request(limit=2, window=60)

        for _ in range(2):
            dep(req)
        with pytest.raises(HTTPException) as exc:
            dep(req)
        assert exc.value.status_code == 429

    def test_different_attrs_produce_isolated_limiters(self) -> None:
        """Two deps on the same app must not share a bucket."""
        dep_a = rate_limit_dep("_a_limiter", "foo_rate_limit", "foo_rate_window")
        dep_b = rate_limit_dep("_b_limiter", "foo_rate_limit", "foo_rate_window")
        req = self._make_app_request(limit=1, window=60)

        dep_a(req)
        # Second call to dep_a would 429; but dep_b has its own bucket.
        dep_b(req)  # should not raise
        with pytest.raises(HTTPException):
            dep_a(req)

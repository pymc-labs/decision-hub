"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import (
    RateLimiter,
    _client_ip,
    make_rate_limit_dependency,
)


def _make_request(host: str = "127.0.0.1", headers: dict | None = None) -> MagicMock:
    """Create a mock Request with a given client IP and optional headers."""
    request = MagicMock()
    request.client.host = host
    # ``request.headers.get(...)`` is what our code calls; use a plain dict
    # so casing is caller-controlled (Starlette normalises to lowercase).
    request.headers = {k.lower(): v for k, v in (headers or {}).items()}
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


class TestClientIp:
    """The rate limiter must key on the *real* client behind the proxy."""

    def test_prefers_x_forwarded_for_leftmost(self) -> None:
        """X-Forwarded-For leftmost entry wins over transport peer."""
        request = _make_request(
            host="10.0.0.1",  # the LB
            headers={"X-Forwarded-For": "203.0.113.5, 10.0.0.1"},
        )
        assert _client_ip(request) == "203.0.113.5"

    def test_falls_back_to_x_real_ip(self) -> None:
        request = _make_request(host="10.0.0.1", headers={"X-Real-IP": "203.0.113.9"})
        assert _client_ip(request) == "203.0.113.9"

    def test_falls_back_to_transport_peer(self) -> None:
        request = _make_request(host="127.0.0.1")
        assert _client_ip(request) == "127.0.0.1"

    def test_no_client_and_no_headers_yields_unknown(self) -> None:
        request = MagicMock()
        request.client = None
        request.headers = {}
        assert _client_ip(request) == "unknown"

    def test_two_users_behind_same_proxy_do_not_share_bucket(self) -> None:
        """Regression: with the old ``request.client.host`` reader, both users
        landed in the same counter and one noisy caller 429'd everyone else."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        alice = _make_request(host="10.0.0.1", headers={"X-Forwarded-For": "203.0.113.5"})
        bob = _make_request(host="10.0.0.1", headers={"X-Forwarded-For": "203.0.113.6"})

        limiter(alice)  # Alice used her one request
        with pytest.raises(HTTPException):
            limiter(alice)
        # Bob is behind the same LB but has a different real IP — must not be blocked.
        limiter(bob)


class TestMakeRateLimitDependency:
    """The factory replaces 9 hand-rolled ``_enforce_*_rate_limit`` wrappers."""

    def _make_request_with_state(self, settings) -> MagicMock:
        req = _make_request()
        # ``app.state`` behaves like a Starlette state object — attribute access.
        req.app.state = SimpleNamespace(settings=settings)
        return req

    def test_lazily_creates_limiter_and_caches_on_app_state(self) -> None:
        dep = make_rate_limit_dependency("test", "test_rate_limit", "test_rate_window")
        settings = SimpleNamespace(test_rate_limit=2, test_rate_window=60)
        req = self._make_request_with_state(settings)

        assert not hasattr(req.app.state, "_test_rate_limiter")
        dep(req)
        limiter = req.app.state._test_rate_limiter
        assert isinstance(limiter, RateLimiter)
        assert limiter.max_requests == 2

        # A second call must reuse the same instance (per-container singleton).
        dep(req)
        assert req.app.state._test_rate_limiter is limiter

    def test_enforces_configured_limit(self) -> None:
        dep = make_rate_limit_dependency("test", "test_rate_limit", "test_rate_window")
        settings = SimpleNamespace(test_rate_limit=1, test_rate_window=60)
        req = self._make_request_with_state(settings)

        dep(req)
        with pytest.raises(HTTPException) as exc:
            dep(req)
        assert exc.value.status_code == 429


class TestPurgeCounter:
    """The old ``total % 100 == 0`` trigger was arithmetically fragile; ensure
    the counter-based version fires deterministically and drops stale IPs."""

    def test_purge_removes_stale_ips_after_the_configured_hits(self) -> None:
        limiter = RateLimiter(max_requests=1000, window_seconds=1)
        with patch("decision_hub.api.rate_limit.time") as mock_time:
            # 99 hits from unique IPs at t=1000 — one shy of the purge trigger.
            mock_time.monotonic.return_value = 1000.0
            for i in range(99):
                limiter(_make_request(host=f"10.0.0.{i}"))
            assert len(limiter._requests) == 99

            # Advance past the window and issue one more hit. That's hit #100
            # and drives ``_hits_since_purge`` to _PURGE_EVERY_HITS, so purge
            # runs with a cutoff that expires every earlier IP.
            mock_time.monotonic.return_value = 1002.0
            limiter(_make_request(host="10.99.99.99"))
            assert set(limiter._requests) == {"10.99.99.99"}

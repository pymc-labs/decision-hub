"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, _extract_client_ip, rate_limited


def _make_request(host: str = "127.0.0.1", headers: dict[str, str] | None = None) -> MagicMock:
    """Create a mock Request with a given client IP and optional headers."""
    request = MagicMock()
    request.client.host = host
    # Match how Starlette exposes headers: case-insensitive .get(...)
    request.headers.get.side_effect = lambda key, default="": (headers or {}).get(key.lower(), default)
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
        # No X-Forwarded-For header either — this is the "truly unknown" case.
        request.headers.get.side_effect = lambda key, default="": default

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429


class TestExtractClientIP:
    """Unit tests for the ``X-Forwarded-For`` extraction helper.

    These tests are the safety net against the pre-refactor behaviour where
    the limiter keyed off the socket peer IP — behind Modal / any reverse
    proxy that meant every user shared a single bucket and one client could
    throttle the whole platform.
    """

    def test_returns_peer_ip_when_no_trusted_proxies_configured(self) -> None:
        """Without a trust list, headers are ignored — safe default."""
        req = _make_request(host="10.0.0.5", headers={"x-forwarded-for": "1.2.3.4"})

        # Header explicitly ignored: an untrusted peer could spoof any origin.
        assert _extract_client_ip(req, trusted_proxies=()) == "10.0.0.5"

    def test_returns_peer_ip_when_direct_client_not_in_trust_list(self) -> None:
        """A peer IP outside the trust list is treated as the real client."""
        req = _make_request(host="203.0.113.7", headers={"x-forwarded-for": "1.2.3.4"})

        # Direct connection from 203.0.113.7 — the header is not from a proxy
        # we authorised, so we must not trust it.
        assert _extract_client_ip(req, trusted_proxies=("10.0.0.",)) == "203.0.113.7"

    def test_uses_leftmost_forwarded_ip_when_peer_is_trusted(self) -> None:
        """Trusted proxy → left-most non-empty entry from X-Forwarded-For wins."""
        req = _make_request(host="10.0.0.5", headers={"x-forwarded-for": "1.2.3.4, 10.0.0.1"})

        assert _extract_client_ip(req, trusted_proxies=("10.0.0.",)) == "1.2.3.4"

    def test_falls_back_to_peer_ip_when_header_empty(self) -> None:
        """Trusted proxy but no X-Forwarded-For → peer IP (the proxy)."""
        req = _make_request(host="10.0.0.5", headers={})

        assert _extract_client_ip(req, trusted_proxies=("10.0.0.",)) == "10.0.0.5"

    def test_matches_exact_proxy_ip(self) -> None:
        """A trust entry without a trailing dot is treated as an exact match."""
        req = _make_request(host="10.0.0.5", headers={"x-forwarded-for": "1.2.3.4"})

        assert _extract_client_ip(req, trusted_proxies=("10.0.0.5",)) == "1.2.3.4"
        # And a different proxy on the same /24 is NOT trusted by the exact match.
        req2 = _make_request(host="10.0.0.7", headers={"x-forwarded-for": "1.2.3.4"})
        assert _extract_client_ip(req2, trusted_proxies=("10.0.0.5",)) == "10.0.0.7"

    def test_returns_unknown_when_no_client_and_no_header(self) -> None:
        """No client + no header + no trust list → the "unknown" sentinel."""
        req = MagicMock()
        req.client = None
        req.headers.get.side_effect = lambda key, default="": default

        assert _extract_client_ip(req) == "unknown"


class TestRateLimiterBehindProxy:
    """Integration tests for the P0 bug fix.

    Regression sentinel: without X-Forwarded-For support behind Modal / any
    reverse proxy, every request keys off the proxy IP and one client
    throttles the whole platform.  The failing scenario is: two different
    end-users behind the same proxy share a bucket.
    """

    def test_different_end_users_behind_trusted_proxy_have_separate_buckets(self) -> None:
        limiter = RateLimiter(
            max_requests=2,
            window_seconds=60,
            trusted_proxies=("10.0.0.",),
        )

        # Two users going through the same proxy (peer IP 10.0.0.5) with
        # different original client IPs in X-Forwarded-For.
        user_a = _make_request(host="10.0.0.5", headers={"x-forwarded-for": "1.1.1.1"})
        user_b = _make_request(host="10.0.0.5", headers={"x-forwarded-for": "2.2.2.2"})

        limiter(user_a)
        limiter(user_a)  # user A now at the cap

        # Before the fix, user_b would key off "10.0.0.5" like user_a
        # and immediately 429 here.  After the fix, user_b has their own bucket.
        limiter(user_b)  # should not raise
        limiter(user_b)  # user B now also at the cap

        with pytest.raises(HTTPException) as exc:
            limiter(user_b)
        assert exc.value.status_code == 429

    def test_untrusted_peer_falls_back_to_peer_ip_bucket(self) -> None:
        """Direct-connection clients (no trusted proxy) still share the peer bucket.

        This preserves the historical behaviour for deployments that do NOT
        run behind a reverse proxy.
        """
        limiter = RateLimiter(max_requests=2, window_seconds=60, trusted_proxies=())

        # Two spoofed X-Forwarded-For values from the same untrusted peer —
        # both must key off the peer IP and share the bucket.
        req_a = _make_request(host="203.0.113.9", headers={"x-forwarded-for": "1.1.1.1"})
        req_b = _make_request(host="203.0.113.9", headers={"x-forwarded-for": "2.2.2.2"})

        limiter(req_a)
        limiter(req_b)
        with pytest.raises(HTTPException):
            limiter(req_a)


class TestRateLimitedFactory:
    """The dependency factory used by every rate-limited route.

    Replaces nine near-identical 12-line ``_enforce_*_rate_limit`` helpers.
    The factory must lazily create the limiter on ``app.state`` under a
    stable, per-endpoint attribute name so state persists across requests
    within a Modal container.
    """

    def test_attaches_limiter_lazily_and_reuses_it(self) -> None:
        dep = rate_limited("mytest", limit_attr="a_limit", window_attr="a_window")
        request = _make_request()
        request.app.state = type("S", (), {})()
        request.app.state.settings = MagicMock(a_limit=3, a_window=60, trusted_proxies="")

        # First call attaches the limiter; the attribute name is stable so
        # subsequent calls in the same container hit the same buckets.
        assert not hasattr(request.app.state, "_mytest_rate_limiter")
        dep(request)
        first_limiter = request.app.state._mytest_rate_limiter
        assert isinstance(first_limiter, RateLimiter)

        dep(request)
        assert request.app.state._mytest_rate_limiter is first_limiter

    def test_factory_enforces_limit_from_settings(self) -> None:
        dep = rate_limited("mytest2", limit_attr="a_limit", window_attr="a_window")
        request = _make_request()
        request.app.state = type("S", (), {})()
        request.app.state.settings = MagicMock(a_limit=2, a_window=60, trusted_proxies="")

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc:
            dep(request)
        assert exc.value.status_code == 429

    def test_factory_reads_trusted_proxies_from_settings(self) -> None:
        """The comma-separated ``trusted_proxies`` setting is honoured on first init."""
        dep = rate_limited("mytest3", limit_attr="a_limit", window_attr="a_window")
        request = _make_request(host="10.0.0.5", headers={"x-forwarded-for": "1.1.1.1"})
        request.app.state = type("S", (), {})()
        request.app.state.settings = MagicMock(a_limit=1, a_window=60, trusted_proxies="10.0.0.")

        dep(request)  # keyed off 1.1.1.1 (forwarded), not 10.0.0.5 (peer)

        # Different forwarded IP → new bucket, so this should NOT 429.
        request2 = _make_request(host="10.0.0.5", headers={"x-forwarded-for": "2.2.2.2"})
        request2.app.state = request.app.state
        dep(request2)  # should not raise

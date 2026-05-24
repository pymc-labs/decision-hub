"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException

from decision_hub.api.rate_limit import RateLimiter, get_or_create_limiter


def _make_request(
    host: str = "127.0.0.1",
    *,
    forwarded_for: str | None = None,
    app: FastAPI | None = None,
) -> MagicMock:
    """Create a mock Request with a given client IP and optional XFF header."""
    request = MagicMock()
    request.client.host = host
    headers: dict[str, str] = {}
    if forwarded_for is not None:
        headers["x-forwarded-for"] = forwarded_for
    request.headers.get.side_effect = lambda key, default=None: headers.get(key.lower(), default)
    if app is not None:
        request.app = app
    return request


class TestRateLimiter:
    """Unit tests for the RateLimiter class."""

    def test_allows_requests_under_limit(self) -> None:
        """Requests within the limit should pass without error."""
        limiter = RateLimiter(max_requests=3, window_seconds=60, trust_forwarded_for=False)
        request = _make_request()

        for _ in range(3):
            limiter(request)  # should not raise

    def test_blocks_requests_over_limit(self) -> None:
        """The request exceeding the limit should raise HTTP 429."""
        limiter = RateLimiter(max_requests=3, window_seconds=60, trust_forwarded_for=False)
        request = _make_request()

        for _ in range(3):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429

    def test_different_ips_have_separate_limits(self) -> None:
        """Each IP has its own counter."""
        limiter = RateLimiter(max_requests=2, window_seconds=60, trust_forwarded_for=False)
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
        limiter = RateLimiter(max_requests=2, window_seconds=1, trust_forwarded_for=False)
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
        limiter = RateLimiter(max_requests=2, window_seconds=60, trust_forwarded_for=False)
        request = _make_request()
        request.client = None

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429


class TestForwardedForHandling:
    """Tests for X-Forwarded-For parsing behind a trusted proxy."""

    def test_xff_left_most_used_when_trusted(self) -> None:
        """The left-most XFF entry is the originating client."""
        limiter = RateLimiter(max_requests=2, window_seconds=60, trust_forwarded_for=True)
        # Same proxy IP but two different real clients should NOT share quota
        req_a = _make_request("10.0.0.99", forwarded_for="1.1.1.1, 10.0.0.99")
        req_b = _make_request("10.0.0.99", forwarded_for="2.2.2.2, 10.0.0.99")

        # Burn client A's quota
        limiter(req_a)
        limiter(req_a)
        with pytest.raises(HTTPException):
            limiter(req_a)

        # Client B should still be allowed despite sharing the proxy IP
        limiter(req_b)

    def test_xff_ignored_when_not_trusted(self) -> None:
        """With trust_forwarded_for=False, all traffic from one proxy IP shares quota."""
        limiter = RateLimiter(max_requests=2, window_seconds=60, trust_forwarded_for=False)
        req_a = _make_request("10.0.0.99", forwarded_for="1.1.1.1")
        req_b = _make_request("10.0.0.99", forwarded_for="2.2.2.2")

        # Same peer IP — both requests count against the same bucket
        limiter(req_a)
        limiter(req_b)
        with pytest.raises(HTTPException):
            limiter(req_a)

    def test_xff_whitespace_stripped(self) -> None:
        """Whitespace around forwarded entries is tolerated."""
        limiter = RateLimiter(max_requests=2, window_seconds=60, trust_forwarded_for=True)
        req = _make_request("10.0.0.99", forwarded_for="  1.2.3.4  ,  proxy ")
        limiter(req)
        limiter(req)
        with pytest.raises(HTTPException):
            limiter(req)

    def test_xff_empty_falls_back_to_client_host(self) -> None:
        """An empty XFF header falls back to the immediate peer address."""
        limiter = RateLimiter(max_requests=2, window_seconds=60, trust_forwarded_for=True)
        req = _make_request("1.1.1.1", forwarded_for="")
        limiter(req)
        limiter(req)
        with pytest.raises(HTTPException):
            limiter(req)


class TestSweepBehavior:
    """Regression tests for the previously broken purge trigger.

    The old implementation called ``_purge_stale`` whenever the total
    timestamp count happened to be divisible by 100 — which is True when
    the count is 0, so an empty limiter triggered the sweep on every
    incoming request.  The replacement uses a deterministic counter so
    the sweep happens at known intervals (every N accepted requests).
    """

    def test_purge_not_triggered_when_cache_empty(self) -> None:
        """Cold start: first request must not trigger a stale sweep."""
        limiter = RateLimiter(max_requests=10, window_seconds=60, trust_forwarded_for=False)

        with patch.object(limiter, "_purge_stale") as purge:
            limiter(_make_request("1.1.1.1"))
            purge.assert_not_called()

    def test_purge_not_triggered_every_request(self) -> None:
        """Steady-state: sweep does not fire on every request."""
        limiter = RateLimiter(max_requests=1000, window_seconds=60, trust_forwarded_for=False)

        with patch.object(limiter, "_purge_stale") as purge:
            for ip_octet in range(50):
                limiter(_make_request(f"10.0.0.{ip_octet}"))
            assert purge.call_count == 0

    def test_purge_triggered_after_sweep_interval(self) -> None:
        """Sweep fires at the documented cadence (every 256 accepted requests)."""
        from decision_hub.api import rate_limit as rl

        limiter = RateLimiter(max_requests=10_000, window_seconds=60, trust_forwarded_for=False)

        with patch.object(limiter, "_purge_stale") as purge:
            for _ in range(rl._SWEEP_EVERY_N_REQUESTS):
                limiter(_make_request("10.0.0.1"))
            assert purge.call_count == 1

    def test_stale_ips_removed_on_sweep(self) -> None:
        """Sweep evicts IPs with no recent activity."""
        limiter = RateLimiter(max_requests=10_000, window_seconds=1, trust_forwarded_for=False)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0

            # 100 distinct one-shot IPs
            for ip_octet in range(100):
                limiter(_make_request(f"10.0.0.{ip_octet}"))
            assert len(limiter._requests) == 100

            # All entries fall out of the window
            mock_time.monotonic.return_value = 1100.0
            # One more request from a fresh IP — drives the counter to
            # 101 which is not yet at the sweep interval, so trigger
            # the sweep explicitly to assert eviction logic.
            limiter(_make_request("10.0.0.200"))
            limiter._purge_stale(cutoff=mock_time.monotonic.return_value - 1)

            # Only the active IP remains
            assert list(limiter._requests.keys()) == ["10.0.0.200"]


class TestGetOrCreateLimiter:
    """The lazy-init factory used by the per-endpoint ``_enforce_*`` helpers."""

    def test_returns_same_instance_across_calls(self) -> None:
        """Subsequent calls with the same name return the cached limiter."""
        app = FastAPI()
        req = _make_request(app=app)

        limiter_a = get_or_create_limiter(req, "search", max_requests=10, window_seconds=60)
        limiter_b = get_or_create_limiter(req, "search", max_requests=99, window_seconds=99)

        # Same instance — args after the first call are ignored, which is
        # the intentional cache behaviour.
        assert limiter_a is limiter_b
        assert limiter_a.max_requests == 10

    def test_different_names_get_independent_limiters(self) -> None:
        """Each named endpoint gets its own limiter on app.state."""
        app = FastAPI()
        req = _make_request(app=app)

        a = get_or_create_limiter(req, "search", 10, 60)
        b = get_or_create_limiter(req, "publish", 5, 60)

        assert a is not b
        assert hasattr(app.state, "_rate_limiter_search")
        assert hasattr(app.state, "_rate_limiter_publish")

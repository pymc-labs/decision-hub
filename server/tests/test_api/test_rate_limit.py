"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, rate_limit_dep


def _make_request(host: str = "127.0.0.1") -> MagicMock:
    """Create a mock Request with a given client IP."""
    request = MagicMock()
    request.client.host = host
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

    def test_sliding_window_expires_oldest_slot(self) -> None:
        """Half-window advance frees exactly one slot — sliding, not fixed."""
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        request = _make_request()

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            limiter(request)  # slot at t=1000
            mock_time.monotonic.return_value = 1020.0
            limiter(request)  # slot at t=1020
            mock_time.monotonic.return_value = 1040.0
            limiter(request)  # slot at t=1040

            # At t=1061 the t=1000 slot has aged out (>60s), leaving 2
            # slots in the window. A new request should be accepted.
            mock_time.monotonic.return_value = 1061.0
            limiter(request)

            # But a second request in that same tick puts us at 3
            # active slots (1020, 1040, 1061) — the next one 429s.
            with pytest.raises(HTTPException):
                limiter(request)

    def test_purges_stale_ip_buckets_after_threshold(self) -> None:
        """Bounded memory: idle IP buckets get evicted after PURGE_INTERVAL requests."""
        limiter = RateLimiter(max_requests=1000, window_seconds=1)
        limiter._PURGE_INTERVAL = 5  # tighten for the test

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            # Populate a bunch of one-shot IPs, all in the same tick.
            for i in range(4):
                limiter(_make_request(f"10.0.0.{i}"))
            assert len(limiter._requests) == 4

            # Advance past the window so those IPs are stale, then hit
            # the purge threshold from a new IP.
            mock_time.monotonic.return_value = 1002.0
            limiter(_make_request("10.0.1.1"))
            # The 5th accepted request triggers the purge; only the
            # fresh 10.0.1.1 bucket should survive.
            assert list(limiter._requests) == ["10.0.1.1"]


class TestRateLimitDep:
    """Tests for the rate_limit_dep factory."""

    def _make_request_with_state(self, host: str = "127.0.0.1"):
        """Build a Request with the settings/state attributes rate_limit_dep reads."""
        settings = SimpleNamespace(
            demo_rate_limit=2,
            demo_rate_window=60,
        )
        state = SimpleNamespace(settings=settings)
        request = MagicMock()
        request.client.host = host
        request.app.state = state
        return request, state

    def test_dep_lazily_creates_one_limiter_per_bucket(self) -> None:
        dep = rate_limit_dep("demo")
        request, state = self._make_request_with_state()

        assert not hasattr(state, "_rate_limiter_demo")
        dep(request)
        first = state._rate_limiter_demo
        assert isinstance(first, RateLimiter)
        assert first.max_requests == 2
        assert first.window_seconds == 60

        # A second call re-uses the cached limiter instance.
        dep(request)
        assert state._rate_limiter_demo is first

    def test_dep_shares_bucket_across_endpoints_with_same_name(self) -> None:
        """Two dependencies for the same bucket share one limiter."""
        dep_a = rate_limit_dep("demo")
        dep_b = rate_limit_dep("demo")
        request, state = self._make_request_with_state()

        dep_a(request)
        dep_b(request)  # exhausts the 2-per-window budget
        with pytest.raises(HTTPException) as exc:
            dep_b(request)
        assert exc.value.status_code == 429
        # And only one limiter was cached.
        assert state._rate_limiter_demo is state._rate_limiter_demo

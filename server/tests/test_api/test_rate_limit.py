"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api import rate_limit as rate_limit_module
from decision_hub.api.rate_limit import RateLimiter, make_rate_limit_dep


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

    def test_memory_is_bounded_under_unique_ip_flood(self) -> None:
        """Tracked-IP dict is capped even when every request uses a fresh IP.

        Without the hard cap, a botnet sweeping IPs would grow the limiter
        dict unboundedly between the periodic purges.
        """
        # Shrink the cap so the test stays fast; restore on teardown.
        original_cap = rate_limit_module._MAX_TRACKED_IPS
        rate_limit_module._MAX_TRACKED_IPS = 50
        try:
            limiter = RateLimiter(max_requests=10, window_seconds=60)
            for i in range(500):
                limiter(_make_request(f"10.0.{i // 256}.{i % 256}"))
            # Cap is enforced lazily on insert, so we may sit at cap+1 briefly,
            # but never grow unboundedly.
            assert len(limiter._requests) <= rate_limit_module._MAX_TRACKED_IPS + 1
        finally:
            rate_limit_module._MAX_TRACKED_IPS = original_cap

    def test_call_count_not_scanned_per_request(self) -> None:
        """Periodic purge uses a monotonic counter, not an O(N) dict sum.

        Smoke test: with many distinct keys, every call must still return
        promptly (~O(1) modulo dict access).  Asserting timing is flaky, so
        we instead assert the counter advances by exactly one per call.
        """
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        for i in range(100):
            limiter(_make_request(f"10.0.0.{i}"))
        assert limiter._call_count == 100


class TestMakeRateLimitDep:
    """Tests for the make_rate_limit_dep factory."""

    def _build_request(self, settings_obj) -> MagicMock:
        """A request whose app.state is a fresh SimpleNamespace with settings."""
        request = MagicMock()
        request.client.host = "127.0.0.1"
        # Use SimpleNamespace so hasattr/getattr/setattr behave normally
        # without MagicMock auto-vivifying attributes.
        request.app.state = SimpleNamespace(settings=settings_obj)
        return request

    def test_factory_creates_isolated_limiters_per_name(self) -> None:
        """Two factories with different names share neither counter nor state."""
        settings = SimpleNamespace(
            a_limit=2,
            a_window=60,
            b_limit=2,
            b_window=60,
        )
        request = self._build_request(settings)
        dep_a = make_rate_limit_dep("a", "a_limit", "a_window")
        dep_b = make_rate_limit_dep("b", "b_limit", "b_window")

        dep_a(request)
        dep_a(request)
        with pytest.raises(HTTPException):
            dep_a(request)
        # Endpoint B uses a separate limiter — A's exhaustion must not leak.
        dep_b(request)
        dep_b(request)

    def test_factory_lazily_caches_limiter_on_app_state(self) -> None:
        """The factory creates the limiter once and reuses it across calls."""
        settings = SimpleNamespace(x_limit=5, x_window=60)
        request = self._build_request(settings)
        dep = make_rate_limit_dep("x", "x_limit", "x_window")

        assert not hasattr(request.app.state, "_x_rate_limiter")
        dep(request)
        first = request.app.state._x_rate_limiter
        dep(request)
        assert request.app.state._x_rate_limiter is first

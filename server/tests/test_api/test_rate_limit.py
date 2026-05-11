"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, make_rate_limit_dependency


def _make_request(host: str = "127.0.0.1") -> MagicMock:
    """Create a mock Request with a given client IP."""
    request = MagicMock()
    request.client.host = host
    return request


def _make_app_request(host: str, settings: SimpleNamespace) -> MagicMock:
    """Create a mock Request bound to a fake app.state with settings."""
    request = MagicMock()
    request.client.host = host
    request.app.state = SimpleNamespace(settings=settings)
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

    def test_stale_ips_purged_on_time_trigger(self) -> None:
        """Stale per-IP buckets are evicted once the window elapses.

        Previously the purge was driven by ``total_requests % 100``,
        which could be skipped entirely when rate-limit drops shifted
        the running total past the modulo boundary. Drive it from
        monotonic time so the dict stays bounded under bursty fan-in
        traffic from many short-lived IPs.
        """
        limiter = RateLimiter(max_requests=5, window_seconds=10)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            # Hit the limiter from 50 distinct IPs once each.
            for i in range(50):
                limiter(_make_request(f"10.0.0.{i}"))
            assert len(limiter._requests) == 50

            # Advance past the window and trigger one more request.
            mock_time.monotonic.return_value = 1050.0
            limiter(_make_request("10.0.0.99"))

            # All 50 previous IPs are stale and should be evicted.
            # Only the IP that just made a request remains.
            assert "10.0.0.99" in limiter._requests
            assert len(limiter._requests) == 1


class TestMakeRateLimitDependency:
    """Tests for the make_rate_limit_dependency factory."""

    def test_caches_limiter_on_app_state(self) -> None:
        """The factory builds a limiter once and reuses it across calls."""
        settings = SimpleNamespace(my_rate_limit=2, my_rate_window=60)
        dep = make_rate_limit_dependency("my", limit_attr="my_rate_limit", window_attr="my_rate_window")

        request = _make_app_request("1.2.3.4", settings)

        dep(request)
        limiter = request.app.state._my_rate_limiter
        assert isinstance(limiter, RateLimiter)
        assert limiter.max_requests == 2
        assert limiter.window_seconds == 60

        dep(request)
        # Same limiter instance is reused on the second call.
        assert request.app.state._my_rate_limiter is limiter

    def test_enforces_limit_through_factory(self) -> None:
        """The dependency raises 429 once the limit is exceeded."""
        settings = SimpleNamespace(my_rate_limit=2, my_rate_window=60)
        dep = make_rate_limit_dependency("my", limit_attr="my_rate_limit", window_attr="my_rate_window")
        request = _make_app_request("1.2.3.4", settings)

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc:
            dep(request)
        assert exc.value.status_code == 429

    def test_different_names_get_independent_limiters(self) -> None:
        """Two factories with different names produce independent limiters."""
        settings = SimpleNamespace(
            a_limit=1,
            a_window=60,
            b_limit=5,
            b_window=60,
        )
        dep_a = make_rate_limit_dependency("a", limit_attr="a_limit", window_attr="a_window")
        dep_b = make_rate_limit_dependency("b", limit_attr="b_limit", window_attr="b_window")
        request = _make_app_request("1.2.3.4", settings)

        dep_a(request)
        # Burns the only token from limiter A; limiter B should still pass.
        with pytest.raises(HTTPException):
            dep_a(request)
        dep_b(request)
        dep_b(request)  # B's bucket is bigger
        assert request.app.state._a_rate_limiter is not request.app.state._b_rate_limiter

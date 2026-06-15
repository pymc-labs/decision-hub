"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import (
    _GC_INTERVAL,
    RateLimiter,
    make_rate_limit_dep,
)


def _make_request(host: str = "127.0.0.1") -> MagicMock:
    """Create a mock Request with a given client IP."""
    request = MagicMock()
    request.client.host = host
    return request


def _make_app_request(host: str = "127.0.0.1", **settings_kwargs) -> MagicMock:
    """Create a mock Request whose .app.state mimics the FastAPI app for factory tests."""
    request = MagicMock()
    request.client.host = host
    request.app.state = SimpleNamespace(settings=SimpleNamespace(**settings_kwargs))
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
        # Detail string is what the user sees -- keep it informative.
        assert "3 requests" in exc_info.value.detail
        assert "60s" in exc_info.value.detail

    def test_different_ips_have_separate_limits(self) -> None:
        """Each IP has its own counter."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        req_a = _make_request("10.0.0.1")
        req_b = _make_request("10.0.0.2")

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


class TestRateLimiterConstruction:
    """Constructor argument validation."""

    @pytest.mark.parametrize("bad_value", [0, -1])
    def test_invalid_max_requests_rejected(self, bad_value: int) -> None:
        with pytest.raises(ValueError, match="max_requests"):
            RateLimiter(max_requests=bad_value, window_seconds=60)

    @pytest.mark.parametrize("bad_value", [0, -1])
    def test_invalid_window_rejected(self, bad_value: int) -> None:
        with pytest.raises(ValueError, match="window_seconds"):
            RateLimiter(max_requests=10, window_seconds=bad_value)


class TestRateLimiterMemoryHygiene:
    """The map of per-IP queues must not grow without bound."""

    def test_idle_ips_are_purged_after_window(self) -> None:
        """IPs that haven't been seen in a full window are removed when GC fires."""
        # max_requests is set high enough that the same IP can drive the
        # GC counter without itself getting rate-limited.
        limiter = RateLimiter(max_requests=_GC_INTERVAL + 100, window_seconds=60)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            # Fan in distinct IPs to populate the map.
            for i in range(50):
                limiter(_make_request(f"10.0.0.{i}"))
            assert len(limiter._requests) == 50

            # Jump past the window so the 50 are stale, then drive enough
            # requests through a fresh IP to trigger the periodic purge.
            mock_time.monotonic.return_value = 1000.0 + 61
            stable_ip = _make_request("10.99.99.99")
            for _ in range(_GC_INTERVAL):
                limiter(stable_ip)

            # The active IP survives; all 50 stale ones are gone.
            assert "10.99.99.99" in limiter._requests
            assert len(limiter._requests) == 1

    def test_purge_does_not_fire_on_every_request(self) -> None:
        """The previous implementation purged on every request whenever the
        map was empty. The counter-based interval must space scans out."""
        limiter = RateLimiter(max_requests=_GC_INTERVAL + 10, window_seconds=60)

        with patch.object(limiter, "_purge_stale", wraps=limiter._purge_stale) as spy:
            for _ in range(_GC_INTERVAL - 1):
                limiter(_make_request())
            assert spy.call_count == 0

            limiter(_make_request())
            assert spy.call_count == 1

    def test_unknown_ip_does_not_implicitly_create_entry(self) -> None:
        """Constructing the limiter and reading state must not seed any bucket."""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        assert len(limiter._requests) == 0


class TestMakeRateLimitDep:
    """Behaviour of the FastAPI dependency factory."""

    def test_creates_named_dependency(self) -> None:
        dep = make_rate_limit_dep("foo", "foo_rate_limit", "foo_rate_window")
        assert dep.__name__ == "_enforce_foo_rate_limit"
        assert "foo_rate_limit" in (dep.__doc__ or "")

    def test_initialises_limiter_lazily_on_app_state(self) -> None:
        dep = make_rate_limit_dep("foo", "foo_limit", "foo_window")
        request = _make_app_request(foo_limit=2, foo_window=60)

        assert not hasattr(request.app.state, "_foo_rate_limiter")
        dep(request)
        assert hasattr(request.app.state, "_foo_rate_limiter")

    def test_reuses_existing_limiter_across_requests(self) -> None:
        dep = make_rate_limit_dep("foo", "foo_limit", "foo_window")
        request = _make_app_request(foo_limit=10, foo_window=60)

        dep(request)
        first = request.app.state._foo_rate_limiter
        dep(request)
        assert request.app.state._foo_rate_limiter is first

    def test_enforces_configured_limit(self) -> None:
        dep = make_rate_limit_dep("foo", "foo_limit", "foo_window")
        request = _make_app_request(foo_limit=2, foo_window=60)

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_independent_endpoints_have_independent_limiters(self) -> None:
        a = make_rate_limit_dep("alpha", "alpha_limit", "alpha_window")
        b = make_rate_limit_dep("beta", "beta_limit", "beta_window")

        # Same app, two distinct deps -- each gets its own counter and key.
        request = _make_app_request(alpha_limit=1, alpha_window=60, beta_limit=1, beta_window=60)

        a(request)
        b(request)  # not blocked even though alpha already saw 1 request

        with pytest.raises(HTTPException):
            a(request)
        with pytest.raises(HTTPException):
            b(request)

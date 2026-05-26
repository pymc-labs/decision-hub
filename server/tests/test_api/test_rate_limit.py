"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api import rate_limit as rate_limit_mod
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

    def test_purges_stale_ips_after_threshold_requests(self) -> None:
        """Idle IP buckets are purged every _PURGE_EVERY_N_REQUESTS calls.

        Regression test: the previous implementation gated purging on
        ``sum(len(v) for v in _requests.values()) % 100 == 0``, which
        depends on instantaneous bucket sizes and can stay just shy of
        the boundary at steady-state, leaking idle IPs indefinitely.
        """
        limiter = RateLimiter(max_requests=1000, window_seconds=1)

        # Issue one request from many distinct IPs, then leave them idle
        # until past the window so each becomes prunable.
        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            for i in range(50):
                limiter(_make_request(f"10.0.0.{i}"))

            # Advance past the window so every prior timestamp is stale.
            mock_time.monotonic.return_value = 1100.0

            # Drive a single hot IP enough times to trigger one purge.
            hot_ip = _make_request("192.168.1.1")
            for _ in range(rate_limit_mod._PURGE_EVERY_N_REQUESTS):
                limiter(hot_ip)

        # All 50 idle IPs should be gone; only the hot IP remains.
        keys = set(limiter._requests.keys())
        assert "192.168.1.1" in keys
        for i in range(50):
            assert f"10.0.0.{i}" not in keys, f"stale IP 10.0.0.{i} was not purged"


class TestMakeRateLimitDep:
    """Tests for the dependency factory used by route modules."""

    def _make_app_request(self, **rate_settings) -> MagicMock:
        """Build a fake Request whose app.state carries settings + an empty registry."""
        request = MagicMock()
        request.client.host = "127.0.0.1"
        # Real SimpleNamespace so attribute-set works without MagicMock auto-attrs.
        request.app.state = SimpleNamespace(settings=SimpleNamespace(**rate_settings))
        return request

    def test_lazily_creates_limiter_from_settings(self) -> None:
        """First call reads {name}_rate_limit / _rate_window from settings."""
        dep = make_rate_limit_dep("publish")
        request = self._make_app_request(publish_rate_limit=2, publish_rate_window=60)

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_reuses_limiter_across_calls(self) -> None:
        """The factory caches one limiter per name on app.state."""
        dep = make_rate_limit_dep("download")
        request = self._make_app_request(download_rate_limit=5, download_rate_window=60)

        dep(request)
        dep(request)

        limiters = request.app.state.rate_limiters
        assert "download" in limiters
        first = limiters["download"]

        dep(request)
        assert limiters["download"] is first

    def test_separate_names_get_separate_limiters(self) -> None:
        """Two factories with different names don't share state."""
        dep_a = make_rate_limit_dep("publish")
        dep_b = make_rate_limit_dep("download")
        request = self._make_app_request(
            publish_rate_limit=1,
            publish_rate_window=60,
            download_rate_limit=1,
            download_rate_window=60,
        )

        dep_a(request)
        # publish bucket is full, but download has its own
        dep_b(request)
        with pytest.raises(HTTPException):
            dep_a(request)
        with pytest.raises(HTTPException):
            dep_b(request)

    def test_dep_has_descriptive_name(self) -> None:
        """The returned callable carries a useful __name__ for tracebacks."""
        dep = make_rate_limit_dep("audit_log")
        assert dep.__name__ == "enforce_audit_log_rate_limit"

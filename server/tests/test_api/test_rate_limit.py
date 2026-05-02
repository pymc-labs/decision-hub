"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter


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


class TestRateLimiterPurge:
    """Stale-IP purge keeps memory bounded."""

    def test_periodic_purge_drops_stale_keys(self) -> None:
        """After enough requests, IPs with only-expired timestamps disappear."""
        limiter = RateLimiter(max_requests=5, window_seconds=10)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            # Seed many distinct IPs at t=0.
            mock_time.monotonic.return_value = 0.0
            for i in range(50):
                limiter(_make_request(f"10.0.0.{i}"))
            assert len(limiter._requests) == 50

            # Jump past the window so all those entries are now stale.
            mock_time.monotonic.return_value = 1000.0

            # Drive enough fresh traffic from one IP to trigger _PURGE_EVERY.
            fresh = _make_request("192.168.1.1")
            for _ in range(RateLimiter._PURGE_EVERY):
                # Reset the per-key list so a single IP can drive many calls
                # without exhausting its own quota.
                limiter._requests["192.168.1.1"] = []
                limiter(fresh)

        # After the periodic purge fires, only the fresh IP should remain.
        assert "192.168.1.1" in limiter._requests
        assert all(k.startswith("192.168.1.") for k in limiter._requests)

    def test_saturation_rejects_new_ip_with_429(self, monkeypatch) -> None:
        """When the tracked-IP cap is hit and nothing is purgeable, reject."""
        # Shrink the cap so the test is fast and obvious.
        monkeypatch.setattr(RateLimiter, "_MAX_TRACKED_KEYS", 10)

        limiter = RateLimiter(max_requests=5, window_seconds=60)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            # Fill at the cap with fresh entries the purge can't reclaim.
            for i in range(10):
                limiter._requests[f"ip-{i}"] = [100.0]

            # The next brand-new IP pushes us over and should be rejected.
            with pytest.raises(HTTPException) as exc_info:
                limiter(_make_request("brand-new-ip"))
            assert exc_info.value.status_code == 429

    def test_saturation_admits_when_purge_frees_space(self, monkeypatch) -> None:
        """If the cap is hit but stale entries exist, purge them and admit."""
        monkeypatch.setattr(RateLimiter, "_MAX_TRACKED_KEYS", 10)

        limiter = RateLimiter(max_requests=5, window_seconds=10)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            # Fill at the cap with stale entries.
            mock_time.monotonic.return_value = 0.0
            for i in range(10):
                limiter._requests[f"ip-{i}"] = [0.0]

            # Jump past the window — all 10 are now purgeable.
            mock_time.monotonic.return_value = 1000.0

            # New IP is admitted; purge reclaims space.
            limiter(_make_request("brand-new-ip"))  # should not raise
            assert "brand-new-ip" in limiter._requests
            assert len(limiter._requests) <= 10

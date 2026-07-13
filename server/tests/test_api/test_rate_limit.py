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

    def test_rejected_request_still_prunes_stale_entries(self) -> None:
        """Even when a request is rate-limited, the internal list is pruned.

        Regression check for a subtle memory leak: the old implementation
        computed a pruned copy of the timestamp list, but only assigned it
        back to the dict on the *allowed* branch. On the reject branch the
        stale list stayed intact, so expired entries accumulated on any IP
        that hit its limit repeatedly.
        """
        limiter = RateLimiter(max_requests=2, window_seconds=1)
        request = _make_request()

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            for _ in range(2):
                limiter(request)

            # Advance past the window — all prior timestamps are now stale.
            mock_time.monotonic.return_value = 1002.0
            # Fill the window again.
            for _ in range(2):
                limiter(request)

            # Rejected request: the internal list should still be pruned so
            # it only contains the two fresh timestamps, not the four total.
            with pytest.raises(HTTPException):
                limiter(request)
            assert len(limiter._requests["127.0.0.1"]) == 2

    def test_purge_stale_removes_inactive_ips(self) -> None:
        """Stale IPs are dropped when the purge counter fires."""
        limiter = RateLimiter(max_requests=1000, window_seconds=1)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            # Register 50 distinct IPs.
            for i in range(50):
                limiter(_make_request(f"10.0.0.{i}"))
            assert len(limiter._requests) == 50

            # Advance past window so those entries are stale, then hit one
            # active IP enough to trip the purge counter (default: 100).
            mock_time.monotonic.return_value = 1002.0
            active = _make_request("192.168.0.1")
            for _ in range(100):
                limiter(active)

            # The purge fires when the counter crosses the threshold — the
            # 50 stale IPs registered earlier should be gone, leaving only
            # the active one.
            assert list(limiter._requests) == ["192.168.0.1"]


class TestRateLimitDep:
    """Factory that returns a FastAPI dependency wired to app.state."""

    def _make_request_with_settings(
        self,
        *,
        limit: int,
        window: int,
        host: str = "127.0.0.1",
    ) -> MagicMock:
        request = _make_request(host)
        request.app.state = SimpleNamespace(
            settings=SimpleNamespace(
                my_rate_limit=limit,
                my_rate_window=window,
            )
        )
        return request

    def test_lazily_creates_limiter_on_first_call(self) -> None:
        """The limiter is only built the first time the dependency runs."""
        dep = rate_limit_dep("my", limit_attr="my_rate_limit", window_attr="my_rate_window")
        request = self._make_request_with_settings(limit=5, window=60)

        assert not hasattr(request.app.state, "_rate_limiter_my")
        dep(request)
        assert isinstance(request.app.state._rate_limiter_my, RateLimiter)

    def test_reuses_existing_limiter_across_requests(self) -> None:
        """A second call finds the cached limiter and does not rebuild it."""
        dep = rate_limit_dep("my", limit_attr="my_rate_limit", window_attr="my_rate_window")
        request = self._make_request_with_settings(limit=5, window=60)

        dep(request)
        first = request.app.state._rate_limiter_my
        dep(request)
        assert request.app.state._rate_limiter_my is first

    def test_enforces_configured_limit(self) -> None:
        """The dependency raises 429 once the caller crosses the settings-driven cap."""
        dep = rate_limit_dep("my", limit_attr="my_rate_limit", window_attr="my_rate_window")
        request = self._make_request_with_settings(limit=2, window=60)

        for _ in range(2):
            dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

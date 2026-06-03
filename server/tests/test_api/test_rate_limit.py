"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import (
    _PURGE_EVERY_N_CALLS,
    RateLimiter,
    get_or_create_limiter,
)


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


class TestStaleIpPurge:
    """The purge ran on ``sum(len(v) for v in requests.values()) % 100``.

    Once timestamps were pruned each call, that sum stayed small (typically
    1 per active key after pruning), and the modulo rarely hit zero except
    by coincidence. The new implementation uses a per-instance counter so
    eviction runs deterministically every N requests regardless of the
    traffic mix.
    """

    def test_idle_ips_eventually_evicted(self) -> None:
        """A key untouched for longer than the window is dropped on purge."""
        limiter = RateLimiter(max_requests=_PURGE_EVERY_N_CALLS * 4, window_seconds=60)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            limiter(_make_request("10.0.0.1"))
            assert "10.0.0.1" in limiter._requests

            # Walk past the rate window so the idle IP is eligible for purge.
            mock_time.monotonic.return_value = 120.0

            # Drive enough live traffic from a different IP to cross the purge
            # threshold; the new counter purges on a fixed cadence regardless
            # of how many distinct IPs are active.
            live = _make_request("10.0.0.2")
            for _ in range(_PURGE_EVERY_N_CALLS):
                limiter(live)

            assert "10.0.0.1" not in limiter._requests
            assert "10.0.0.2" in limiter._requests

    def test_purge_cadence_does_not_depend_on_per_ip_rate(self) -> None:
        """One IP hammering the same endpoint still triggers the purge.

        Under the old implementation, a single hot IP would prune its own
        timestamps on every call, leaving ``total`` clamped at 1 and the
        purge would only trigger on a numerical coincidence. The counter
        approach must fire after exactly ``_PURGE_EVERY_N_CALLS`` calls.
        """
        limiter = RateLimiter(max_requests=_PURGE_EVERY_N_CALLS * 4, window_seconds=60)
        hot = _make_request("10.0.0.99")

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            limiter(_make_request("10.0.0.1"))
            mock_time.monotonic.return_value = 120.0

            for _ in range(_PURGE_EVERY_N_CALLS):
                limiter(hot)

            assert "10.0.0.1" not in limiter._requests


class TestGetOrCreateLimiter:
    """The lazy-init helper used by every public route module."""

    def test_creates_limiter_on_first_call(self) -> None:
        state = SimpleNamespace()
        limiter = get_or_create_limiter(
            state,
            "_some_limiter",
            max_requests=5,
            window_seconds=60,
        )

        assert isinstance(limiter, RateLimiter)
        assert limiter.max_requests == 5
        assert state._some_limiter is limiter

    def test_returns_same_instance_on_subsequent_calls(self) -> None:
        """Repeated calls must reuse the same RateLimiter — otherwise the
        sliding-window counters would reset on every request."""
        state = SimpleNamespace()
        first = get_or_create_limiter(state, "_attr", max_requests=5, window_seconds=60)
        second = get_or_create_limiter(state, "_attr", max_requests=999, window_seconds=999)

        assert first is second, "must reuse, not rebuild"
        # Updated args are ignored — the original instance is what counts.
        assert first.max_requests == 5

    def test_different_attribute_names_create_distinct_limiters(self) -> None:
        state = SimpleNamespace()
        a = get_or_create_limiter(state, "_limit_a", max_requests=1, window_seconds=60)
        b = get_or_create_limiter(state, "_limit_b", max_requests=1, window_seconds=60)

        assert a is not b

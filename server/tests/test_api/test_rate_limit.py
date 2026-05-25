"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, client_ip


def _make_request(
    host: str = "127.0.0.1",
    *,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Create a mock Request with a given client IP and optional headers."""
    request = MagicMock()
    request.client.host = host
    request.headers = headers or {}
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
        request.headers = {}

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429

    def test_pruning_keeps_per_key_list_bounded(self) -> None:
        """Pruning runs on every call so a hot key's bucket stays bounded.

        Before the refactor, the per-key list was only pruned when the
        global total happened to be a multiple of 100. Under steady
        traffic from a single key this never fired, letting the list
        grow without bound for the whole window. After the refactor
        the per-key prune is unconditional.
        """
        limiter = RateLimiter(max_requests=1000, window_seconds=1)
        request = _make_request()

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            for _ in range(10):
                limiter(request)
            # Advance past the window — all 10 timestamps are now stale.
            mock_time.monotonic.return_value = 1002.0
            limiter(request)
            bucket = limiter._requests["127.0.0.1"]
            # Only the post-advance call should remain — the 10 stale
            # entries must have been pruned.
            assert len(bucket) == 1

    def test_full_prune_drops_idle_keys(self) -> None:
        """After the prune interval elapses, idle keys are evicted."""
        limiter = RateLimiter(max_requests=5, window_seconds=1)
        # Seed a few idle keys.
        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            for i in range(5):
                limiter(_make_request(f"10.0.0.{i}"))
            assert len(limiter._requests) == 5

            # Jump well past the prune interval. The next request
            # should sweep the stale keys out.
            mock_time.monotonic.return_value = 100_000.0
            limiter(_make_request("10.0.0.99"))
            # Only the most recent key remains.
            assert list(limiter._requests.keys()) == ["10.0.0.99"]

    def test_evicts_to_cap_under_key_flood(self) -> None:
        """When the tracked-key dict exceeds the cap, oldest keys are dropped."""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        # Tighten the cap so we don't have to flood with 50k keys.
        with patch("decision_hub.api.rate_limit._MAX_TRACKED_KEYS", 10):
            for i in range(15):
                limiter(_make_request(f"10.0.0.{i}"))
            # Capped at 10 after the post-call eviction.
            assert len(limiter._requests) <= 10
            # The most-recent key must still be present — eviction
            # drops oldest, not newest.
            assert "10.0.0.14" in limiter._requests


class TestClientIp:
    """``client_ip`` honours proxy headers iff the caller opts in."""

    def test_ignores_xff_when_proxy_not_trusted(self) -> None:
        """By default we never trust X-Forwarded-For — it's user-controllable."""
        request = _make_request(
            "203.0.113.1",
            headers={"x-forwarded-for": "1.2.3.4"},
        )
        assert client_ip(request) == "203.0.113.1"

    def test_uses_xff_when_proxy_trusted(self) -> None:
        """When opted in, the first XFF entry is the real client."""
        request = _make_request(
            "10.0.0.1",  # the proxy
            headers={"x-forwarded-for": "203.0.113.5, 10.0.0.1"},
        )
        assert client_ip(request, trust_proxy_headers=True) == "203.0.113.5"

    def test_falls_back_to_x_real_ip(self) -> None:
        """X-Real-IP is the fallback when XFF is absent."""
        request = _make_request(
            "10.0.0.1",
            headers={"x-real-ip": "198.51.100.2"},
        )
        assert client_ip(request, trust_proxy_headers=True) == "198.51.100.2"

    def test_strips_whitespace_around_xff_entry(self) -> None:
        """Proxies often add a space after the comma — handle gracefully."""
        request = _make_request(
            "10.0.0.1",
            headers={"x-forwarded-for": "  203.0.113.9  , 10.0.0.1"},
        )
        assert client_ip(request, trust_proxy_headers=True) == "203.0.113.9"

    def test_returns_unknown_when_no_client(self) -> None:
        """Missing client and missing headers => 'unknown' bucket."""
        request = MagicMock()
        request.client = None
        request.headers = {}
        assert client_ip(request) == "unknown"

    def test_proxy_aware_limiter_buckets_by_real_ip(self) -> None:
        """Two requests from different real clients via the same proxy are independent."""
        limiter = RateLimiter(
            max_requests=1,
            window_seconds=60,
            trust_proxy_headers=True,
        )
        # Both come in through the same proxy peer; only the XFF
        # header distinguishes them.
        req_a = _make_request("10.0.0.1", headers={"x-forwarded-for": "1.1.1.1"})
        req_b = _make_request("10.0.0.1", headers={"x-forwarded-for": "2.2.2.2"})

        limiter(req_a)
        limiter(req_b)  # different real IP — should not be rate-limited

        with pytest.raises(HTTPException):
            limiter(req_a)  # second call from 1.1.1.1 over its limit

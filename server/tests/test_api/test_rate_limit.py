"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter


def _make_request(host: str = "127.0.0.1", xff: str | None = None) -> MagicMock:
    """Create a mock Request with a given socket-peer IP and optional XFF header."""
    request = MagicMock()
    request.client.host = host
    headers: dict[str, str] = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    request.headers.get = headers.get
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
        request.headers.get = {}.get

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429

    def test_x_forwarded_for_beats_socket_peer(self) -> None:
        """Behind a proxy every request has the same socket peer; XFF must decide.

        Without honoring XFF, all traffic through Modal / a load balancer
        shares one bucket and either everyone gets 429 or the limiter is
        effectively disabled.
        """
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        proxy_ip = "10.0.0.1"
        req_a = _make_request(host=proxy_ip, xff="203.0.113.5")
        req_b = _make_request(host=proxy_ip, xff="198.51.100.9")

        for _ in range(2):
            limiter(req_a)

        # req_a is exhausted; req_b -- same socket peer, different real client --
        # must still be allowed.
        limiter(req_b)  # should not raise

        with pytest.raises(HTTPException):
            limiter(req_a)

    def test_x_forwarded_for_first_hop_wins(self) -> None:
        """Only the first entry of a multi-hop XFF header identifies the client."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        request = _make_request(host="10.0.0.1", xff="203.0.113.5, 198.51.100.9, 10.0.0.1")

        limiter(request)  # first call fills the bucket for 203.0.113.5
        with pytest.raises(HTTPException):
            limiter(request)

        # A different first-hop should be unaffected even though intermediate hops match
        other = _make_request(host="10.0.0.1", xff="203.0.113.6, 198.51.100.9, 10.0.0.1")
        limiter(other)  # should not raise

    def test_empty_x_forwarded_for_falls_back_to_socket_peer(self) -> None:
        """An empty XFF header must not be used as the bucket key."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        req = _make_request(host="10.0.0.1", xff="   ")

        limiter(req)
        with pytest.raises(HTTPException):
            limiter(req)  # same socket peer, still blocked

    def test_purge_bounds_memory_under_scan(self) -> None:
        """Requests from N unique IPs must not leave N entries around forever.

        The previous implementation triggered pruning based on an O(N) scan
        that grew with traffic; the counter-based trigger caps memory to
        roughly one purge interval's worth of stale keys.
        """
        limiter = RateLimiter(max_requests=5, window_seconds=1)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            for i in range(RateLimiter._PURGE_INTERVAL):
                limiter(_make_request(host=f"10.0.0.{i}"))

            # Advance well past the window so every previous entry is stale,
            # then drive the counter to the next purge boundary.
            mock_time.monotonic.return_value = 2000.0
            for i in range(RateLimiter._PURGE_INTERVAL):
                limiter(_make_request(host=f"10.99.99.{i}"))

        # First-generation keys are stale; only second-generation keys survive.
        remaining = set(limiter._requests.keys())
        assert remaining == {f"10.99.99.{i}" for i in range(RateLimiter._PURGE_INTERVAL)}

    def test_purge_trigger_is_constant_time(self) -> None:
        """The purge trigger must not scan every bucket on every request.

        Regression guard: the previous implementation summed len() across all
        bucket lists on every call, degrading the hot path to O(N-IPs).
        """
        limiter = RateLimiter(max_requests=1_000_000, window_seconds=60)
        # Seed thousands of buckets to make an accidental O(N) scan visible.
        for i in range(5_000):
            limiter(_make_request(host=f"10.0.{i // 256}.{i % 256}"))
        # If the request-count-based trigger is intact, _request_count matches
        # the number of calls exactly (no per-request scan needed).
        assert limiter._request_count == 5_000

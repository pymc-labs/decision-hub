"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

import threading
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.datastructures import State

from decision_hub.api.rate_limit import (
    RateLimiter,
    _client_key,
    get_or_create_limiter,
)


def _make_request(host: str = "127.0.0.1", forwarded_for: str | None = None) -> MagicMock:
    """Create a mock Request with a given client IP.

    Uses a real dict for ``request.headers`` so the ``.get()`` return
    value is a real Optional[str], not a MagicMock (which would be
    truthy and defeat the header check).
    """
    request = MagicMock()
    request.client.host = host
    headers = {}
    if forwarded_for is not None:
        headers["x-forwarded-for"] = forwarded_for
    request.headers = headers
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


class TestClientKey:
    """Unit tests for the X-Forwarded-For handling in ``_client_key``."""

    def test_prefers_first_x_forwarded_for_entry(self) -> None:
        """The first XFF entry (original client) is used as the key."""
        req = _make_request(host="10.0.0.99", forwarded_for="203.0.113.4, 10.0.0.1")
        assert _client_key(req) == "203.0.113.4"

    def test_falls_back_to_client_host(self) -> None:
        """Without XFF, ``request.client.host`` is used."""
        req = _make_request(host="10.0.0.5")
        assert _client_key(req) == "10.0.0.5"

    def test_empty_x_forwarded_for_ignored(self) -> None:
        """An empty XFF value falls back to client.host, not the empty string."""
        req = _make_request(host="10.0.0.7", forwarded_for="")
        assert _client_key(req) == "10.0.0.7"

    def test_xff_gives_distinct_limits_behind_proxy(self) -> None:
        """Two clients behind the same proxy get separate limiter buckets."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        # Same proxy IP, different real client IPs.
        req_a = _make_request(host="10.0.0.99", forwarded_for="203.0.113.4")
        req_b = _make_request(host="10.0.0.99", forwarded_for="203.0.113.5")
        limiter(req_a)
        # Without XFF handling both requests would share one bucket and
        # this second call would raise; with XFF it must not.
        limiter(req_b)


class TestPurgeAccumulator:
    """Regression tests for the O(1) purge trigger."""

    def test_purge_runs_after_interval(self) -> None:
        """After _PURGE_INTERVAL admissions, stale keys are cleared."""
        limiter = RateLimiter(max_requests=1000, window_seconds=1)
        # Seed a stale key from an "old" IP.
        limiter._requests["old-ip"] = [0.0]  # timestamp way in the past

        # Drive PURGE_INTERVAL admissions from a different key.
        for i in range(limiter._PURGE_INTERVAL):
            limiter(_make_request(host=f"1.1.1.{i % 250}"))

        # The stale key should have been swept.
        assert "old-ip" not in limiter._requests


class TestGetOrCreateLimiter:
    """Regression tests for the lazy-init race."""

    def test_returns_same_limiter_across_calls(self) -> None:
        """A second call must return the previously-stored limiter."""
        state = State()
        first = get_or_create_limiter(state, "_test_limiter", 10, 60)
        second = get_or_create_limiter(state, "_test_limiter", 10, 60)
        assert first is second

    def test_concurrent_init_produces_one_instance(self) -> None:
        """Concurrent first-access must not produce two limiter instances.

        Without the init lock, two threads both fail the ``hasattr`` /
        ``getattr`` check and both instantiate a fresh RateLimiter; one
        setattr wins and the other's accounting is silently lost.
        """
        state = State()
        results: list[RateLimiter] = []
        start = threading.Event()

        def race() -> None:
            start.wait()
            results.append(get_or_create_limiter(state, "_race_limiter", 10, 60))

        threads = [threading.Thread(target=race) for _ in range(16)]
        for t in threads:
            t.start()
        start.set()
        for t in threads:
            t.join()

        # All threads must have observed the same instance.
        assert len({id(r) for r in results}) == 1

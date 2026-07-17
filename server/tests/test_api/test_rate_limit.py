"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, make_rate_limit_dependency


def _make_request(host: str = "127.0.0.1", xff: str | None = None) -> MagicMock:
    """Create a mock Request with a given client IP and optional XFF header.

    Uses a real dict for headers so the code path exercising
    ``request.headers.get('x-forwarded-for')`` sees a proper miss when
    the header isn't set (a bare MagicMock would return a truthy mock).
    """
    request = MagicMock()
    request.client.host = host
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    request.headers.get.side_effect = headers.get
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
        request.headers.get.return_value = None

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429

    def test_x_forwarded_for_is_preferred_over_client_host(self) -> None:
        """X-Forwarded-For's leftmost entry beats request.client.host.

        The proxy's IP would otherwise collapse every caller into one
        bucket. Confirm two callers behind the same proxy end up in
        separate buckets when they present different XFF values.
        """
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        proxy_ip = "10.0.0.99"
        req_a = _make_request(host=proxy_ip, xff="203.0.113.1")
        req_b = _make_request(host=proxy_ip, xff="203.0.113.2")

        limiter(req_a)
        limiter(req_b)  # different XFF → different bucket → still allowed

        with pytest.raises(HTTPException):
            limiter(req_a)  # A's bucket is now full

    def test_x_forwarded_for_uses_leftmost_entry(self) -> None:
        """XFF is a comma-separated chain; the original client is leftmost."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        req = _make_request(host="10.0.0.99", xff="203.0.113.5, 10.0.0.1, 10.0.0.2")

        limiter(req)
        with pytest.raises(HTTPException):
            limiter(req)


class TestMakeRateLimitDependency:
    """Unit tests for the dependency factory that replaces the 8 copy-pasted helpers."""

    def _make_state_and_settings(self, max_requests: int, window: int) -> tuple[SimpleNamespace, SimpleNamespace]:
        settings = SimpleNamespace(_test_max=max_requests, _test_window=window)
        state = SimpleNamespace(settings=settings)
        return state, settings

    def test_lazily_builds_and_caches_limiter(self) -> None:
        """First call constructs a limiter and stores it on app.state; later calls reuse it."""
        dep = make_rate_limit_dependency("_test_limiter", "_test_max", "_test_window")
        state, _ = self._make_state_and_settings(max_requests=3, window=60)
        request = MagicMock()
        request.app.state = state
        request.client.host = "1.2.3.4"
        request.headers.get.return_value = None

        dep(request)
        first = state._test_limiter
        assert isinstance(first, RateLimiter)
        assert first.max_requests == 3
        assert first.window_seconds == 60

        dep(request)
        assert state._test_limiter is first  # cached, not rebuilt

    def test_enforces_limit(self) -> None:
        """The returned dependency actually invokes the underlying limiter."""
        dep = make_rate_limit_dependency("_lim", "_test_max", "_test_window")
        state, _ = self._make_state_and_settings(max_requests=2, window=60)
        request = MagicMock()
        request.app.state = state
        request.client.host = "1.2.3.4"
        request.headers.get.return_value = None

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_concurrent_first_call_creates_only_one_limiter(self) -> None:
        """Under a burst of cold-start requests only one limiter is built.

        The old ``if not hasattr(state, ...): state.x = RateLimiter(...)``
        pattern let two threads both see the missing attribute and
        create competing limiters — the first burst of requests would
        be undercounted because half of them hit the discarded limiter.
        """
        dep = make_rate_limit_dependency("_lim", "_test_max", "_test_window")
        state, _ = self._make_state_and_settings(max_requests=10, window=60)

        seen: list[RateLimiter] = []
        barrier = threading.Barrier(20)

        def worker() -> None:
            req = MagicMock()
            req.app.state = state
            req.client.host = f"10.0.0.{threading.get_ident() % 200}"
            req.headers.get.return_value = None
            barrier.wait()
            dep(req)
            seen.append(state._lim)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Every thread must have observed the exact same limiter object.
        assert len({id(x) for x in seen}) == 1

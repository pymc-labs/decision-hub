"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, rate_limit


def _make_request(host: str = "127.0.0.1", *, forwarded_for: str | None = None) -> MagicMock:
    """Create a mock Request with a given client IP and optional X-Forwarded-For."""
    request = MagicMock()
    request.client.host = host
    headers: dict[str, str] = {}
    if forwarded_for is not None:
        headers["x-forwarded-for"] = forwarded_for
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
        request.headers.get = {}.get

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429


class TestForwardedForKeying:
    """When trust_forwarded_for=True the limiter must key by X-Forwarded-For.

    Without this, a shared load-balancer IP would collapse every real
    caller into one bucket, effectively disabling the rate limiter or
    (worse) 429-ing everyone the moment the LB crosses the threshold.
    """

    def test_uses_forwarded_for_when_trusted(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=60, trust_forwarded_for=True)
        # Same LB IP, different real clients -- must have independent buckets.
        req_a = _make_request(host="lb.internal", forwarded_for="1.2.3.4")
        req_b = _make_request(host="lb.internal", forwarded_for="5.6.7.8")

        for _ in range(2):
            limiter(req_a)
        with pytest.raises(HTTPException):
            limiter(req_a)

        limiter(req_b)  # different client, still allowed

    def test_uses_leftmost_token_of_forwarded_for_chain(self) -> None:
        """XFF may be a comma-separated chain -- the original client is left-most."""
        limiter = RateLimiter(max_requests=2, window_seconds=60, trust_forwarded_for=True)
        req = _make_request(host="lb.internal", forwarded_for="1.2.3.4, 10.0.0.1, 10.0.0.2")

        for _ in range(2):
            limiter(req)
        with pytest.raises(HTTPException):
            limiter(req)

    def test_ignores_forwarded_for_when_untrusted(self) -> None:
        """With trust_forwarded_for=False, the header must NOT be honored.

        Otherwise a caller in a trust-nothing environment (local dev,
        no LB) could just spoof the header to sidestep the limit.
        """
        limiter = RateLimiter(max_requests=2, window_seconds=60, trust_forwarded_for=False)
        # All requests come from the same socket peer; the spoofed XFF must be ignored.
        req_a = _make_request(host="127.0.0.1", forwarded_for="1.2.3.4")
        req_b = _make_request(host="127.0.0.1", forwarded_for="5.6.7.8")

        for _ in range(2):
            limiter(req_a)
        with pytest.raises(HTTPException):
            limiter(req_b)  # same peer, different spoofed XFF -- still blocked

    def test_falls_back_to_client_host_when_forwarded_for_empty(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=60, trust_forwarded_for=True)
        # Explicit empty header should behave like no header at all.
        req = _make_request(host="1.2.3.4", forwarded_for="")

        for _ in range(2):
            limiter(req)
        with pytest.raises(HTTPException):
            limiter(req)


class TestPurgeStale:
    """Bounded memory growth: stale IPs are pruned periodically."""

    def test_purge_removes_ips_with_no_recent_activity(self) -> None:
        limiter = RateLimiter(max_requests=100, window_seconds=1)
        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            for i in range(10):
                limiter(_make_request(f"10.0.0.{i}"))

            # All 10 IPs are tracked.
            assert len(limiter._requests) == 10

            # Advance past the window and trigger the purge.
            mock_time.monotonic.return_value = 200.0
            with patch("decision_hub.api.rate_limit._PURGE_INTERVAL", 1):
                limiter(_make_request("10.0.0.99"))

            # Every previously-tracked IP had no request in the current
            # window and should have been evicted; only the fresh IP remains.
            assert set(limiter._requests.keys()) == {"10.0.0.99"}


class TestRateLimitFactory:
    """The ``rate_limit(name)`` factory replaces per-endpoint _enforce_* helpers."""

    def _fake_state(self, **settings) -> SimpleNamespace:
        state = SimpleNamespace()
        state.settings = SimpleNamespace(**settings)
        return state

    def test_lazy_init_reads_from_settings(self) -> None:
        state = self._fake_state(
            publish_rate_limit=2,
            publish_rate_window=60,
            trust_forwarded_for=True,
        )
        request = _make_request()
        request.app.state = state

        dep = rate_limit("publish")

        for _ in range(2):
            dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_limiter_is_cached_on_app_state(self) -> None:
        state = self._fake_state(
            publish_rate_limit=100,
            publish_rate_window=60,
            trust_forwarded_for=True,
        )
        request = _make_request()
        request.app.state = state

        dep = rate_limit("publish")
        dep(request)

        first = state._rate_limiter_publish
        dep(request)
        # Same limiter instance persists across calls (per-container state).
        assert state._rate_limiter_publish is first

    def test_different_names_get_separate_limiters(self) -> None:
        state = self._fake_state(
            publish_rate_limit=1,
            publish_rate_window=60,
            list_skills_rate_limit=100,
            list_skills_rate_window=60,
            trust_forwarded_for=True,
        )
        request = _make_request()
        request.app.state = state

        publish_dep = rate_limit("publish")
        list_dep = rate_limit("list_skills")

        publish_dep(request)
        with pytest.raises(HTTPException):
            publish_dep(request)  # exceeded (limit=1)

        # A different endpoint is a different bucket -- still allowed.
        list_dep(request)

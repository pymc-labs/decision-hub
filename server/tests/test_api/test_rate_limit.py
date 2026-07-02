"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, rate_limit_dependency


def _make_request(
    host: str = "127.0.0.1",
    xff: str | None = None,
) -> MagicMock:
    """Create a mock Request with a given client IP and optional X-Forwarded-For."""
    request = MagicMock()
    request.client.host = host
    request.headers = {}
    if xff is not None:
        request.headers = {"x-forwarded-for": xff}
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


class TestTrustedProxy:
    """Behaviour behind a load balancer that adds X-Forwarded-For."""

    def test_xff_ignored_when_proxies_untrusted(self) -> None:
        """With trusted_proxy_count=0, XFF is ignored (dev / direct traffic)."""
        limiter = RateLimiter(max_requests=1, window_seconds=60, trusted_proxy_count=0)
        # Two "different" client IPs via XFF but the same peer -> should share bucket.
        req_a = _make_request(host="10.0.0.1", xff="1.2.3.4")
        req_b = _make_request(host="10.0.0.1", xff="5.6.7.8")

        limiter(req_a)
        with pytest.raises(HTTPException):
            limiter(req_b)

    def test_xff_used_when_proxies_trusted(self) -> None:
        """With trusted_proxy_count=1, XFF's right-most entry is the caller IP."""
        limiter = RateLimiter(max_requests=1, window_seconds=60, trusted_proxy_count=1)
        # Same peer (LB) but two different real callers via XFF.
        req_a = _make_request(host="10.0.0.1", xff="1.2.3.4")
        req_b = _make_request(host="10.0.0.1", xff="5.6.7.8")

        limiter(req_a)
        limiter(req_b)  # different caller -> separate bucket

        # Same caller re-hitting -> now blocked.
        with pytest.raises(HTTPException):
            limiter(_make_request(host="10.0.0.1", xff="1.2.3.4"))

    def test_xff_untrusted_hop_is_not_used(self) -> None:
        """A caller can't spoof by adding a fake entry to the left of XFF.

        With trusted_proxy_count=1, only the right-most entry (the one
        the trusted LB added) is honoured. Entries the client itself
        prepended are ignored.
        """
        limiter = RateLimiter(max_requests=1, window_seconds=60, trusted_proxy_count=1)
        # Same real caller (LB adds their peer at the right) but the
        # untrusted client tried to inject different "originator" IPs.
        req_a = _make_request(host="10.0.0.1", xff="9.9.9.9, 1.2.3.4")
        req_b = _make_request(host="10.0.0.1", xff="8.8.8.8, 1.2.3.4")

        limiter(req_a)
        with pytest.raises(HTTPException):
            limiter(req_b)

    def test_xff_shorter_than_trusted_count_clamps(self) -> None:
        """If the chain is shorter than expected, use the left-most entry."""
        limiter = RateLimiter(max_requests=1, window_seconds=60, trusted_proxy_count=5)
        req = _make_request(host="10.0.0.1", xff="1.2.3.4")
        limiter(req)
        with pytest.raises(HTTPException):
            limiter(_make_request(host="10.0.0.1", xff="1.2.3.4"))


class TestPurge:
    """Stale IPs are purged on a time interval rather than a fragile modulo."""

    def test_stale_entries_are_purged(self) -> None:
        """A bucket for an IP with no recent activity is dropped after the interval."""
        limiter = RateLimiter(max_requests=10, window_seconds=1)
        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            limiter(_make_request("1.1.1.1"))
            assert "1.1.1.1" in limiter._requests

            # Advance past the window and the purge interval.
            mock_time.monotonic.return_value = 100.0 + RateLimiter._PURGE_INTERVAL_SECONDS + 5
            limiter(_make_request("2.2.2.2"))

            assert "1.1.1.1" not in limiter._requests
            assert "2.2.2.2" in limiter._requests

    def test_purge_does_not_run_on_every_request(self) -> None:
        """The interval throttles purge so it stays cheap on hot paths."""
        limiter = RateLimiter(max_requests=100, window_seconds=60)
        with (
            patch.object(limiter, "_purge_stale") as spy,
            patch("decision_hub.api.rate_limit.time") as mock_time,
        ):
            mock_time.monotonic.return_value = 100.0
            for _ in range(20):
                limiter(_make_request("1.1.1.1"))
            # First hit triggers a purge (last_purge=0 << now); subsequent
            # hits within the interval must not.
            assert spy.call_count == 1


class TestFactory:
    """rate_limit_dependency lazily attaches a shared limiter to app.state."""

    def _make_app_and_request(self) -> tuple[SimpleNamespace, MagicMock]:
        state = SimpleNamespace(
            settings=SimpleNamespace(
                foo_rate_limit=2,
                foo_rate_window=60,
                trusted_proxy_count=0,
            )
        )
        app = SimpleNamespace(state=state)
        request = MagicMock()
        request.app = app
        request.client.host = "1.2.3.4"
        request.headers = {}
        return state, request

    def test_lazy_init_and_reuse(self) -> None:
        dep = rate_limit_dependency("foo")
        state, request = self._make_app_and_request()

        assert not hasattr(state, "_foo_rate_limiter")
        dep(request)
        limiter = state._foo_rate_limiter
        assert isinstance(limiter, RateLimiter)
        dep(request)
        # Same limiter re-used across calls.
        assert state._foo_rate_limiter is limiter

    def test_enforces_configured_limit(self) -> None:
        dep = rate_limit_dependency("foo")
        _, request = self._make_app_and_request()
        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_passes_through_trusted_proxy_count(self) -> None:
        dep = rate_limit_dependency("foo")
        state, request = self._make_app_and_request()
        state.settings.trusted_proxy_count = 1
        dep(request)
        assert state._foo_rate_limiter.trusted_proxy_count == 1

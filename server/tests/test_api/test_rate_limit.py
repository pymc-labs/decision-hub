"""Tests for decision_hub.api.rate_limit — per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import (
    _LIMITER_SPECS,
    RateLimiter,
    get_rate_limiter,
    rate_limited,
    register_rate_limiters,
)


def _make_request(host: str = "127.0.0.1", forwarded_for: str | None = None) -> MagicMock:
    """Create a mock Request with a given peer IP and optional XFF header."""
    request = MagicMock()
    request.client.host = host
    headers: dict[str, str] = {}
    if forwarded_for is not None:
        headers["x-forwarded-for"] = forwarded_for
    request.headers.get.side_effect = lambda name, default=None: headers.get(name.lower(), default)
    return request


class TestRateLimiter:
    """Unit tests for the RateLimiter class."""

    def test_allows_requests_under_limit(self) -> None:
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        request = _make_request()

        for _ in range(3):
            limiter(request)  # should not raise

    def test_blocks_requests_over_limit(self) -> None:
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        request = _make_request()

        for _ in range(3):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429

    def test_different_ips_have_separate_limits(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        req_a = _make_request("10.0.0.1")
        req_b = _make_request("10.0.0.2")

        for _ in range(2):
            limiter(req_a)

        with pytest.raises(HTTPException):
            limiter(req_a)

        limiter(req_b)  # other IP unaffected

    def test_window_expiry_resets_limit(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=1)
        request = _make_request()

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            for _ in range(2):
                limiter(request)

            with pytest.raises(HTTPException):
                limiter(request)

            mock_time.monotonic.return_value = 1001.5
            limiter(request)  # window slid past

    def test_no_client_uses_unknown_key(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        request = MagicMock()
        request.client = None
        request.headers.get.return_value = None

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429


class TestForwardedForHandling:
    """When deployed behind a trusted proxy, key on the original client IP."""

    def test_xff_off_by_default_keys_on_peer(self) -> None:
        """Without trust_forwarded_for, all callers behind a proxy share a bucket.

        This is the historical behaviour — we keep a test for it so a
        future change that silently flips the default is caught.
        """
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        # Both requests look like they come from the same proxy IP, but
        # have different XFF headers.
        req_a = _make_request("10.0.0.1", forwarded_for="203.0.113.1")
        req_b = _make_request("10.0.0.1", forwarded_for="203.0.113.2")

        for _ in range(2):
            limiter(req_a)
        with pytest.raises(HTTPException):
            limiter(req_b)

    def test_xff_on_splits_buckets_per_real_client(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=60, trust_forwarded_for=True)
        req_a = _make_request("10.0.0.1", forwarded_for="203.0.113.1")
        req_b = _make_request("10.0.0.1", forwarded_for="203.0.113.2")

        for _ in range(2):
            limiter(req_a)
        # Different real client → still under its own limit.
        limiter(req_b)

    def test_xff_takes_leftmost_only(self) -> None:
        limiter = RateLimiter(max_requests=1, window_seconds=60, trust_forwarded_for=True)
        # Two callers, both passing through the same intermediate. The
        # leftmost entry identifies the real client.
        req_a = _make_request("10.0.0.1", forwarded_for="203.0.113.5, 10.0.0.2")
        req_b = _make_request("10.0.0.1", forwarded_for="203.0.113.99, 10.0.0.2")

        limiter(req_a)
        limiter(req_b)  # different leftmost IP → separate bucket

    def test_xff_falls_back_to_peer_when_header_blank(self) -> None:
        limiter = RateLimiter(max_requests=1, window_seconds=60, trust_forwarded_for=True)
        req = _make_request("10.0.0.42", forwarded_for="   ")
        limiter(req)
        # Second call from the same peer should be blocked even though
        # the XFF header was blank — we fell back to the peer IP.
        with pytest.raises(HTTPException):
            limiter(req)


class TestSlidingWindowStorage:
    """Verify the deque-backed timestamp store stays bounded."""

    def test_old_timestamps_are_evicted_on_each_call(self) -> None:
        limiter = RateLimiter(max_requests=100, window_seconds=10)
        request = _make_request()

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            for _ in range(50):
                limiter(request)
            # 50 timestamps recorded.
            assert len(limiter._requests["127.0.0.1"]) == 50

            # Jump forward past the window — next call should leave only
            # the new timestamp.
            mock_time.monotonic.return_value = 100.0
            limiter(request)
            assert len(limiter._requests["127.0.0.1"]) == 1

    def test_idle_keys_are_purged(self) -> None:
        """After many calls, stale per-IP keys are dropped from the dict."""
        from decision_hub.api.rate_limit import _PRUNE_INTERVAL

        limiter = RateLimiter(max_requests=10_000, window_seconds=10)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            # Touch a wide range of unique keys.
            for i in range(50):
                limiter(_make_request(f"10.0.0.{i}"))
            assert len(limiter._requests) == 50

            # Slide past the window and then drive enough calls from a
            # single key to trip the prune interval.
            mock_time.monotonic.return_value = 1000.0
            keep = _make_request("9.9.9.9")
            for _ in range(_PRUNE_INTERVAL):
                limiter(keep)

            # All the original IPs should be gone — only the active key
            # remains.
            assert "9.9.9.9" in limiter._requests
            assert all(k == "9.9.9.9" for k in limiter._requests)


class TestRegisterRateLimiters:
    """The factory wires every spec into app.state and rate_limited() resolves them."""

    def test_register_creates_all_named_limiters(self) -> None:
        app = MagicMock()
        app.state = MagicMock(spec=[])

        settings = MagicMock()
        # Provide both the rate and window attribute for each spec, plus
        # the proxy-trust flag.
        for spec in _LIMITER_SPECS:
            setattr(settings, spec.max_attr, 5)
            setattr(settings, spec.window_attr, 60)
        settings.trust_forwarded_for = False

        register_rate_limiters(app, settings)

        assert set(app.state.rate_limiters) == {spec.name for spec in _LIMITER_SPECS}
        for limiter in app.state.rate_limiters.values():
            assert isinstance(limiter, RateLimiter)
            assert limiter.max_requests == 5
            assert limiter.window_seconds == 60

    def test_rate_limited_dependency_uses_registered_limiter(self) -> None:
        app = MagicMock()
        app.state.rate_limiters = {
            "search": RateLimiter(max_requests=1, window_seconds=60),
        }
        request = _make_request()
        request.app = app

        dep = rate_limited("search")
        dep(request)
        with pytest.raises(HTTPException):
            dep(request)

    def test_get_rate_limiter_missing_name_raises(self) -> None:
        app = MagicMock()
        app.state.rate_limiters = {}
        request = _make_request()
        request.app = app

        with pytest.raises(KeyError):
            get_rate_limiter(request, "nonexistent")

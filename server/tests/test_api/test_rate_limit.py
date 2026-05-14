"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window limiter,
the eager registry, and the ``rate_limit(name)`` Depends factory."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import (
    RateLimiter,
    RateLimiterRegistry,
    build_rate_limiter_registry,
    rate_limit,
)


def _make_request(host: str = "127.0.0.1") -> MagicMock:
    """Create a mock Request with a given client IP."""
    request = MagicMock()
    request.client.host = host
    return request


class _FakeClock:
    """Manually-advanced clock for deterministic time-based tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now += seconds


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
        clock = _FakeClock(start=1000.0)
        limiter = RateLimiter(max_requests=2, window_seconds=1, clock=clock)
        request = _make_request()

        for _ in range(2):
            limiter(request)
        with pytest.raises(HTTPException):
            limiter(request)

        clock.tick(1.5)  # past the 1s window
        limiter(request)  # should not raise

    def test_burst_at_window_boundary(self) -> None:
        """Two bursts spaced exactly one window apart should both succeed."""
        clock = _FakeClock(start=0.0)
        limiter = RateLimiter(max_requests=2, window_seconds=10, clock=clock)
        request = _make_request()

        limiter(request)
        limiter(request)
        clock.tick(10.001)
        limiter(request)
        limiter(request)  # would 429 if old timestamps weren't pruned

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


class TestRateLimiterRegistry:
    """Eager registry replaces the old lazy ``hasattr(state, ...)`` pattern."""

    def test_get_unregistered_raises(self) -> None:
        registry = RateLimiterRegistry()
        with pytest.raises(KeyError, match="not registered"):
            registry.get("missing")

    def test_double_register_raises(self) -> None:
        registry = RateLimiterRegistry()
        registry.register("foo", RateLimiter(max_requests=1, window_seconds=1))
        with pytest.raises(ValueError, match="already registered"):
            registry.register("foo", RateLimiter(max_requests=1, window_seconds=1))

    def test_build_registers_all_known_limiters(self) -> None:
        """``build_rate_limiter_registry`` must wire every limiter the routes
        expect — a missing entry would 500 the corresponding route."""
        settings = MagicMock()
        # Provide every *_rate_limit / *_rate_window field with sane numerics.
        for attr in (
            "search_rate_limit",
            "search_rate_window",
            "auth_rate_limit",
            "auth_rate_window",
            "list_skills_rate_limit",
            "list_skills_rate_window",
            "resolve_rate_limit",
            "resolve_rate_window",
            "similar_skills_rate_limit",
            "similar_skills_rate_window",
            "download_rate_limit",
            "download_rate_window",
            "audit_log_rate_limit",
            "audit_log_rate_window",
            "publish_rate_limit",
            "publish_rate_window",
            "scan_report_rate_limit",
            "scan_report_rate_window",
        ):
            setattr(settings, attr, 10)

        registry = build_rate_limiter_registry(settings)

        for name in (
            "search",
            "auth",
            "list_skills",
            "resolve",
            "similar_skills",
            "download",
            "audit_log",
            "publish",
            "scan_report",
        ):
            assert isinstance(registry.get(name), RateLimiter)


class TestRateLimitDependency:
    """``rate_limit(name)`` returns a FastAPI dependency that defers to the
    request's app-state registry."""

    def test_dependency_invokes_named_limiter(self) -> None:
        registry = RateLimiterRegistry()
        registry.register("foo", RateLimiter(max_requests=1, window_seconds=60))

        request = _make_request()
        request.app.state.rate_limiters = registry

        dep = rate_limit("foo")
        dep(request)  # first call ok
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

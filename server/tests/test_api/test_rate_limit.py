"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, client_ip, rate_limiter_dep


def _make_request(host: str = "127.0.0.1", headers: dict[str, str] | None = None) -> MagicMock:
    """Create a mock Request with a given client IP and optional headers."""
    request = MagicMock()
    request.client.host = host
    request.headers = headers or {}
    return request


class TestClientIP:
    """The shared ``client_ip`` helper used by every limiter dependency."""

    def test_prefers_x_forwarded_for_leftmost(self) -> None:
        """X-Forwarded-For takes precedence and we use the original client (leftmost)."""
        request = _make_request(
            host="10.0.0.1",
            headers={"x-forwarded-for": "203.0.113.42, 10.0.0.5, 10.0.0.1"},
        )
        assert client_ip(request) == "203.0.113.42"

    def test_strips_whitespace_in_xff_chain(self) -> None:
        request = _make_request(
            host="10.0.0.1",
            headers={"x-forwarded-for": "   198.51.100.7  ,  10.0.0.1"},
        )
        assert client_ip(request) == "198.51.100.7"

    def test_falls_back_to_x_real_ip(self) -> None:
        request = _make_request(host="10.0.0.1", headers={"x-real-ip": "203.0.113.99"})
        assert client_ip(request) == "203.0.113.99"

    def test_falls_back_to_peer_address(self) -> None:
        request = _make_request(host="10.0.0.1")
        assert client_ip(request) == "10.0.0.1"

    def test_returns_unknown_when_no_client(self) -> None:
        request = MagicMock()
        request.client = None
        request.headers = {}
        assert client_ip(request) == "unknown"

    def test_empty_xff_header_is_ignored(self) -> None:
        """An empty XFF (some proxies send it empty) must not become the key."""
        request = _make_request(host="10.0.0.1", headers={"x-forwarded-for": ""})
        assert client_ip(request) == "10.0.0.1"

    def test_xff_with_only_commas_falls_through(self) -> None:
        request = _make_request(
            host="10.0.0.1",
            headers={"x-forwarded-for": "  ", "x-real-ip": "203.0.113.7"},
        )
        assert client_ip(request) == "203.0.113.7"


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

    def test_different_xff_clients_behind_same_peer_have_separate_limits(self) -> None:
        """Two real clients behind the same edge proxy must not share a bucket.

        This is the bug-fix regression: previously the limiter keyed on
        ``request.client.host`` (the proxy IP), so one noisy client could
        DoS every other client sharing the edge.
        """
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        # Both share the same direct peer (the LB) but XFF reveals
        # different original clients.
        req_a = _make_request(host="10.0.0.1", headers={"x-forwarded-for": "203.0.113.1"})
        req_b = _make_request(host="10.0.0.1", headers={"x-forwarded-for": "203.0.113.2"})

        limiter(req_a)
        limiter(req_a)
        with pytest.raises(HTTPException):
            limiter(req_a)

        # Client B is untouched because it has its own key.
        limiter(req_b)

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


class TestRateLimiterDep:
    """The factory that replaces the 9 hand-rolled ``_enforce_*`` wrappers."""

    def _state_app(self, **settings_overrides) -> MagicMock:
        """Build a minimal app/request pair with settings on app.state."""
        settings = MagicMock(
            list_skills_rate_limit=2,
            list_skills_rate_window=60,
            publish_rate_limit=1,
            publish_rate_window=60,
        )
        for k, v in settings_overrides.items():
            setattr(settings, k, v)

        request = _make_request()
        # MagicMock auto-creates attribute access by default; we need
        # ``getattr(state, "_rate_limiter_foo", None)`` to start as None
        # so the factory builds a fresh limiter.
        state = MagicMock(spec=["settings"])
        state.settings = settings
        request.app.state = state
        return request

    def test_factory_builds_limiter_lazily_and_shares_across_calls(self) -> None:
        request = self._state_app()
        dep = rate_limiter_dep("list_skills")

        # Two calls should reuse the same limiter, so the second consumes
        # the second of the two-per-window budget.
        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_factory_reads_setting_names_from_provided_prefix(self) -> None:
        request = self._state_app()
        dep = rate_limiter_dep("publish")

        dep(request)  # consumes the only-allowed publish/window
        with pytest.raises(HTTPException):
            dep(request)

    def test_different_factories_get_separate_limiters(self) -> None:
        """``rate_limiter_dep("a")`` and ``rate_limiter_dep("b")`` must not collide."""
        request = self._state_app()
        list_dep = rate_limiter_dep("list_skills")
        pub_dep = rate_limiter_dep("publish")

        # Saturate publish (limit=1) and verify list_skills is unaffected.
        pub_dep(request)
        with pytest.raises(HTTPException):
            pub_dep(request)
        list_dep(request)  # different setting prefix, separate state

"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, _client_key, make_rate_limit_dependency


def _make_request(host: str = "127.0.0.1", forwarded_for: str | None = None) -> MagicMock:
    """Create a mock Request with a given client IP and optional XFF header."""
    request = MagicMock()
    request.client.host = host
    request.headers = {"x-forwarded-for": forwarded_for} if forwarded_for else {}
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
    """Client identification — fixes the Modal LB single-bucket bug."""

    def test_uses_xff_leftmost_when_present(self) -> None:
        """Behind a proxy, leftmost X-Forwarded-For is the original caller."""
        request = _make_request(host="10.0.0.1", forwarded_for="1.2.3.4, 10.0.0.1")
        assert _client_key(request) == "1.2.3.4"

    def test_falls_back_to_client_host_without_xff(self) -> None:
        request = _make_request(host="10.0.0.1")
        assert _client_key(request) == "10.0.0.1"

    def test_xff_with_single_value(self) -> None:
        request = _make_request(host="10.0.0.1", forwarded_for="1.2.3.4")
        assert _client_key(request) == "1.2.3.4"

    def test_xff_whitespace_handled(self) -> None:
        request = _make_request(host="10.0.0.1", forwarded_for="  1.2.3.4 , 5.6.7.8")
        assert _client_key(request) == "1.2.3.4"

    def test_empty_xff_falls_back(self) -> None:
        request = _make_request(host="10.0.0.1", forwarded_for="")
        assert _client_key(request) == "10.0.0.1"

    def test_two_clients_through_proxy_have_separate_buckets(self) -> None:
        """Without XFF support, both these clients would share one bucket
        (request.client.host == LB IP for both)."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        req_a = _make_request(host="10.0.0.1", forwarded_for="1.2.3.4")
        req_b = _make_request(host="10.0.0.1", forwarded_for="5.6.7.8")

        limiter(req_a)
        # If we wrongly shared a bucket, this would 429
        limiter(req_b)


class TestMakeRateLimitDependency:
    """The factory used by every API route to wire up its limiter."""

    def _build_app_state(self, limit: int, window: int) -> MagicMock:
        state = MagicMock(spec=[])
        state.settings = MagicMock()
        state.settings.test_rate_limit = limit
        state.settings.test_rate_window = window
        return state

    def test_lazy_init_then_reuse(self) -> None:
        """First call constructs the limiter, subsequent calls reuse it."""
        dep = make_rate_limit_dependency("test")
        state = self._build_app_state(limit=2, window=60)
        request = _make_request()
        request.app.state = state

        dep(request)
        first = state._test_rate_limiter
        dep(request)
        assert state._test_rate_limiter is first  # not re-created

    def test_enforces_configured_limit(self) -> None:
        dep = make_rate_limit_dependency("test")
        state = self._build_app_state(limit=2, window=60)
        request = _make_request()
        request.app.state = state

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_each_name_has_own_state_attr(self) -> None:
        """Two factories with different names must not share buckets."""
        dep_a = make_rate_limit_dependency("a_thing")
        dep_b = make_rate_limit_dependency("b_thing")
        state = MagicMock(spec=[])
        state.settings = MagicMock()
        state.settings.a_thing_rate_limit = 1
        state.settings.a_thing_rate_window = 60
        state.settings.b_thing_rate_limit = 1
        state.settings.b_thing_rate_window = 60
        request = _make_request()
        request.app.state = state

        dep_a(request)
        # If they shared a bucket, this would 429
        dep_b(request)

"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from collections import deque
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api import rate_limit as rate_limit_module
from decision_hub.api.rate_limit import RateLimiter, make_rate_limit_dependency


def _make_request(host: str = "127.0.0.1") -> MagicMock:
    """Create a mock Request with a given client IP."""
    request = MagicMock()
    request.client.host = host
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

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429

    def test_uses_deque_not_list(self) -> None:
        """Per-IP timestamps are stored in a deque (no per-request reallocation)."""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        request = _make_request()

        limiter(request)
        assert isinstance(limiter._requests["127.0.0.1"], deque)

    def test_deque_reused_across_calls(self) -> None:
        """The per-IP deque is mutated in place, not replaced each call."""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        request = _make_request()

        limiter(request)
        first_deque = limiter._requests["127.0.0.1"]
        limiter(request)
        assert limiter._requests["127.0.0.1"] is first_deque

    def test_periodic_purge_drops_stale_ips(self, monkeypatch) -> None:
        """After enough requests, stale IPs are dropped from the internal table."""
        monkeypatch.setattr(rate_limit_module, "_PURGE_EVERY_N_REQUESTS", 3)
        limiter = RateLimiter(max_requests=1, window_seconds=1)

        with patch.object(rate_limit_module, "time") as mock_time:
            # Stale entries at t=1000
            mock_time.monotonic.return_value = 1000.0
            limiter(_make_request("10.0.0.1"))
            limiter(_make_request("10.0.0.2"))

            # A well past their window — enough requests to trigger purge
            mock_time.monotonic.return_value = 1500.0
            limiter(_make_request("10.0.0.3"))

            # Two of the first three requests were counted, third triggers purge.
            # Stale keys (10.0.0.1, 10.0.0.2) should be gone; only 10.0.0.3 remains.
            assert set(limiter._requests) == {"10.0.0.3"}
            assert limiter._request_counter == 0


class TestMakeRateLimitDependency:
    """Unit tests for the ``make_rate_limit_dependency`` factory."""

    def _make_state_and_request(self, host: str = "127.0.0.1") -> tuple[SimpleNamespace, MagicMock]:
        settings = SimpleNamespace(
            search_rate_limit=2,
            search_rate_window=60,
        )
        state = SimpleNamespace(settings=settings)
        request = MagicMock()
        request.client.host = host
        request.app.state = state
        return state, request

    def test_lazy_init_on_first_call(self) -> None:
        state, request = self._make_state_and_request()
        assert not hasattr(state, "_search_rate_limiter")

        dep = make_rate_limit_dependency("search")
        dep(request)

        assert isinstance(state._search_rate_limiter, RateLimiter)
        assert state._search_rate_limiter.max_requests == 2
        assert state._search_rate_limiter.window_seconds == 60

    def test_limiter_shared_across_calls(self) -> None:
        state, request = self._make_state_and_request()
        dep = make_rate_limit_dependency("search")

        dep(request)
        limiter_after_first = state._search_rate_limiter
        dep(request)

        assert state._search_rate_limiter is limiter_after_first

    def test_enforces_limit(self) -> None:
        _state, request = self._make_state_and_request()
        dep = make_rate_limit_dependency("search")

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_dependency_name_reflects_endpoint(self) -> None:
        """The returned callable's __name__ is set for readable stack traces."""
        dep = make_rate_limit_dependency("publish")
        assert dep.__name__ == "_enforce_publish_rate_limit"

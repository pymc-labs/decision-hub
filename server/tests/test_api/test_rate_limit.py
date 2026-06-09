"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, rate_limit_dependency


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

    def test_reads_do_not_create_empty_entries(self) -> None:
        """``defaultdict`` would create an entry on every key touch.

        With a plain dict, an IP only appears in the store after it makes
        a real request, so pruning can actually reclaim the slot.
        """
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        request = _make_request("1.2.3.4")

        # Before any request, the store is empty — accessing it inside the
        # limiter must NOT create a default empty list for the key.
        assert "1.2.3.4" not in limiter._requests

        limiter(request)
        assert "1.2.3.4" in limiter._requests

    def test_stale_ips_are_purged_after_burst(self) -> None:
        """A burst of one-shot IPs shouldn't grow the store unbounded.

        The purge fires deterministically every 100 requests regardless of
        how many IPs are in the store. Once it runs after the window has
        rolled over, every stale entry is reclaimed.
        """
        limiter = RateLimiter(max_requests=1, window_seconds=1)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            # 100 distinct IPs at t=0. This fires the purge but everything
            # is still fresh so nothing is reclaimed yet.
            for i in range(100):
                limiter(_make_request(f"10.0.0.{i}"))
            assert len(limiter._requests) == 100

            # Move past the window so all earlier entries become stale.
            mock_time.monotonic.return_value = 1000.0
            # 100 fresh requests — the 100th trips the next purge, which
            # reclaims every stale entry from t=0.
            for i in range(100):
                limiter(_make_request(f"10.0.1.{i}"))

        # Only the t=1000 IPs remain — the t=0 batch is gone.
        keys = set(limiter._requests.keys())
        assert all(k.startswith("10.0.1.") for k in keys)
        assert len(keys) == 100


# ---------------------------------------------------------------------------
# rate_limit_dependency factory
# ---------------------------------------------------------------------------


class TestRateLimitDependency:
    """Tests for the FastAPI dependency factory.

    The factory replaces ~80 lines of duplicated ``_enforce_*_rate_limit``
    boilerplate across registry_routes, search_routes and auth_routes.
    """

    def _make_request_with_state(self, host: str, settings) -> MagicMock:
        request = MagicMock()
        request.client.host = host
        # SimpleNamespace gives us attribute access without auto-creating
        # mock attributes for ``hasattr`` checks.
        request.app.state = SimpleNamespace(settings=settings)
        return request

    def test_lazy_init_uses_settings_fields(self) -> None:
        """First call reads the configured limit/window from settings."""
        settings = SimpleNamespace(my_limit=2, my_window=60)
        dep = rate_limit_dependency("test_a", "my_limit", "my_window")

        request = self._make_request_with_state("1.1.1.1", settings)

        dep(request)
        dep(request)

        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_one_limiter_per_name_on_state(self) -> None:
        """The limiter is cached on app.state and reused across requests."""
        settings = SimpleNamespace(my_limit=10, my_window=60)
        dep = rate_limit_dependency("test_b", "my_limit", "my_window")

        request = self._make_request_with_state("1.1.1.1", settings)
        dep(request)

        first_limiter = request.app.state._rate_limiter_test_b
        dep(request)
        assert request.app.state._rate_limiter_test_b is first_limiter

    def test_different_names_get_independent_limiters(self) -> None:
        """Two dependencies with different names don't share state."""
        settings = SimpleNamespace(la=1, wa=60, lb=1, wb=60)
        dep_a = rate_limit_dependency("alpha", "la", "wa")
        dep_b = rate_limit_dependency("beta", "lb", "wb")

        request = self._make_request_with_state("9.9.9.9", settings)

        dep_a(request)
        # Limiter 'alpha' is now full for this IP, but 'beta' is fresh.
        dep_b(request)
        with pytest.raises(HTTPException):
            dep_a(request)
        with pytest.raises(HTTPException):
            dep_b(request)

    def test_dependency_name_is_set(self) -> None:
        """The returned callable has a discoverable __name__ for debugging."""
        dep = rate_limit_dependency("foo", "x", "y")
        assert dep.__name__ == "enforce_foo_rate_limit"

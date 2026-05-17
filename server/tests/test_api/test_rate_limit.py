"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, make_rate_limit_dep


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

    def test_purge_stale_runs_every_interval(self) -> None:
        """Stale-IP purge should run every _PURGE_INTERVAL calls, not on every call.

        The previous implementation summed every value list to drive the
        check; this guards the new O(1) counter approach against regressing.
        """
        limiter = RateLimiter(max_requests=1000, window_seconds=60)
        with patch.object(RateLimiter, "_purge_stale") as mock_purge:
            for _ in range(RateLimiter._PURGE_INTERVAL - 1):
                limiter(_make_request())
            assert mock_purge.call_count == 0
            limiter(_make_request())
            assert mock_purge.call_count == 1
            for _ in range(RateLimiter._PURGE_INTERVAL):
                limiter(_make_request())
            assert mock_purge.call_count == 2


def _make_app_request(settings: object, *, host: str = "127.0.0.1") -> MagicMock:
    """Build a mock Request whose app.state mirrors the production layout."""
    request = MagicMock()
    request.client.host = host
    # ``hasattr(state, ...)`` is used by the limiter cache, so use a
    # SimpleNamespace as the state container rather than MagicMock which
    # would auto-create any attribute.
    state = SimpleNamespace()
    state.settings = settings
    request.app.state = state
    return request


class TestMakeRateLimitDep:
    """Unit tests for the make_rate_limit_dep factory."""

    def test_builds_limiter_from_settings(self) -> None:
        """The factory reads {name}_rate_limit and {name}_rate_window from settings."""
        settings = SimpleNamespace(foo_rate_limit=2, foo_rate_window=60)
        dep = make_rate_limit_dep("foo")
        request = _make_app_request(settings)

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_caches_limiter_per_name_on_app_state(self) -> None:
        """Repeated calls reuse the same limiter; separate names get separate counters."""
        settings = SimpleNamespace(
            a_rate_limit=1,
            a_rate_window=60,
            b_rate_limit=1,
            b_rate_window=60,
        )
        dep_a = make_rate_limit_dep("a")
        dep_b = make_rate_limit_dep("b")
        request = _make_app_request(settings)

        dep_a(request)
        # 'a' should now be exhausted but 'b' is independent.
        with pytest.raises(HTTPException):
            dep_a(request)
        dep_b(request)
        with pytest.raises(HTTPException):
            dep_b(request)

        # The shared state holds exactly one limiter per name.
        limiters = request.app.state._rate_limiters
        assert set(limiters.keys()) == {"a", "b"}
        assert limiters["a"] is not limiters["b"]

    def test_missing_setting_raises_attribute_error(self) -> None:
        """A typo in the dependency name surfaces as AttributeError on first call.

        This is a sanity guard: silent fallback to "no limit" would be a
        worse failure mode than a clear AttributeError at startup.
        """
        settings = SimpleNamespace()  # no matching attrs
        dep = make_rate_limit_dep("ghost")
        request = _make_app_request(settings)
        with pytest.raises(AttributeError):
            dep(request)

    def test_dependency_name_is_set_for_debuggability(self) -> None:
        """The returned dep callable carries a useful __name__ and docstring."""
        dep = make_rate_limit_dep("search")
        assert dep.__name__ == "rate_limit_search"
        assert dep.__doc__ is not None
        assert "search" in dep.__doc__

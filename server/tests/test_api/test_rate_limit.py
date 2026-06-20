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

    def test_purges_stale_ips_on_interval(self) -> None:
        """Stale IPs are removed once purge_interval calls have elapsed."""
        limiter = RateLimiter(max_requests=10, window_seconds=1, purge_interval=4)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            # Three different stale IPs at t=1000
            for ip in ("10.0.0.1", "10.0.0.2", "10.0.0.3"):
                limiter(_make_request(ip))

            assert len(limiter._requests) == 3

            # Advance well past the window so all three are stale, then ping a
            # fourth IP enough times to trigger the purge (purge_interval=4 →
            # next call after this is the 4th total, which fires the sweep).
            mock_time.monotonic.return_value = 2000.0
            limiter(_make_request("10.0.0.4"))

            # 10.0.0.4 is fresh; the three older entries were swept.
            assert set(limiter._requests.keys()) == {"10.0.0.4"}


class TestMakeRateLimitDep:
    """Tests for the make_rate_limit_dep factory.

    The factory wires up a per-app lazy singleton from
    ``settings.{name}_rate_limit`` / ``settings.{name}_rate_window`` and caches
    the limiter on ``request.app.state`` under ``_{name}_rate_limiter``.
    """

    def _make_request_with_state(self, host: str = "127.0.0.1") -> tuple[MagicMock, SimpleNamespace]:
        """Build a Request whose ``app.state`` is a real attribute container.

        We need a real ``SimpleNamespace`` rather than a MagicMock for the
        state so ``setattr`` and ``getattr(..., None)`` behave normally — the
        factory uses both.
        """
        state = SimpleNamespace()
        state.settings = SimpleNamespace(
            foo_rate_limit=2,
            foo_rate_window=60,
        )
        request = MagicMock()
        request.client.host = host
        request.app.state = state
        return request, state

    def test_factory_creates_per_name_singleton(self) -> None:
        """Repeated calls reuse the same limiter cached on app.state."""
        dep = make_rate_limit_dep("foo")
        req, state = self._make_request_with_state()

        dep(req)
        first = state._foo_rate_limiter
        dep(req)
        second = state._foo_rate_limiter

        assert first is second
        assert isinstance(first, RateLimiter)
        assert first.max_requests == 2
        assert first.window_seconds == 60

    def test_factory_enforces_limit_from_settings(self) -> None:
        """The factory-built dep raises 429 once the settings limit is reached."""
        dep = make_rate_limit_dep("foo")
        req, _state = self._make_request_with_state()

        dep(req)
        dep(req)
        with pytest.raises(HTTPException) as exc_info:
            dep(req)
        assert exc_info.value.status_code == 429

    def test_factory_isolates_distinct_names(self) -> None:
        """Two factory deps with different names get independent limiters."""
        dep_foo = make_rate_limit_dep("foo")
        dep_bar = make_rate_limit_dep("bar")

        state = SimpleNamespace()
        state.settings = SimpleNamespace(
            foo_rate_limit=1,
            foo_rate_window=60,
            bar_rate_limit=1,
            bar_rate_window=60,
        )
        req = MagicMock()
        req.client.host = "127.0.0.1"
        req.app.state = state

        # Burning through foo's allowance must not affect bar's.
        dep_foo(req)
        with pytest.raises(HTTPException):
            dep_foo(req)
        dep_bar(req)  # bar's bucket is independent

    def test_factory_sets_descriptive_name(self) -> None:
        """The returned callable has a useful ``__name__`` for stack traces."""
        dep = make_rate_limit_dep("publish")
        assert dep.__name__ == "_enforce_publish_rate_limit"

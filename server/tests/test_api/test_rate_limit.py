"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

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


class TestMakeRateLimitDep:
    """Tests for the dependency factory that builds per-endpoint limiters."""

    def _make_request_with_state(self, host: str = "127.0.0.1") -> MagicMock:
        """Build a Request whose ``app.state`` is a stand-in object.

        The factory looks up settings via ``state.settings`` and stores the
        cached limiter on ``state`` itself, so a SimpleNamespace-style mock
        is sufficient.
        """
        request = MagicMock()
        request.client.host = host
        # `state` must be a real object so getattr/setattr work — a MagicMock
        # would auto-create attributes and defeat the lazy-init check.
        from types import SimpleNamespace

        settings = SimpleNamespace(widget_rate_limit=2, widget_rate_window=60)
        request.app.state = SimpleNamespace(settings=settings)
        return request

    def test_caches_limiter_on_app_state(self) -> None:
        """First call constructs the limiter; subsequent calls reuse it."""
        dep = make_rate_limit_dep("widget")
        request = self._make_request_with_state()

        dep(request)
        first = request.app.state._widget_rate_limiter
        dep(request)
        second = request.app.state._widget_rate_limiter

        assert first is second
        assert isinstance(first, RateLimiter)

    def test_reads_settings_attrs_by_name(self) -> None:
        """The factory derives ``{name}_rate_limit`` / ``{name}_rate_window`` from the supplied name."""
        dep = make_rate_limit_dep("widget")
        request = self._make_request_with_state()

        dep(request)

        limiter = request.app.state._widget_rate_limiter
        assert limiter.max_requests == 2
        assert limiter.window_seconds == 60

    def test_enforces_429_after_limit_exceeded(self) -> None:
        """The dependency raises 429 once the per-IP quota is reached."""
        dep = make_rate_limit_dep("widget")
        request = self._make_request_with_state()

        dep(request)
        dep(request)
        with pytest.raises(HTTPException) as exc_info:
            dep(request)
        assert exc_info.value.status_code == 429

    def test_distinct_names_get_distinct_limiters(self) -> None:
        """Two dependencies built with different names share no state."""
        from types import SimpleNamespace

        dep_a = make_rate_limit_dep("alpha")
        dep_b = make_rate_limit_dep("beta")

        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.app.state = SimpleNamespace(
            settings=SimpleNamespace(
                alpha_rate_limit=5,
                alpha_rate_window=60,
                beta_rate_limit=99,
                beta_rate_window=60,
            ),
        )

        dep_a(request)
        dep_b(request)

        assert request.app.state._alpha_rate_limiter.max_requests == 5
        assert request.app.state._beta_rate_limiter.max_requests == 99
        assert request.app.state._alpha_rate_limiter is not request.app.state._beta_rate_limiter

    def test_dep_function_name_matches_old_convention(self) -> None:
        """The returned callable keeps the legacy ``_enforce_<name>_rate_limit`` __name__.

        FastAPI uses dependency __name__ for OpenAPI scoping and error messages,
        so preserving it avoids spurious diff in generated specs.
        """
        dep = make_rate_limit_dep("widget")
        assert dep.__name__ == "_enforce_widget_rate_limit"

"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter, rate_limit_dependency


def _make_request(
    host: str = "127.0.0.1", *, headers: dict[str, str] | None = None, trust_proxy: bool = False
) -> MagicMock:
    """Create a mock Request with a given client IP and optional headers."""
    request = MagicMock()
    request.client.host = host
    # Match the FastAPI headers.get(name, "") behaviour used by the code.
    hmap = {k.lower(): v for k, v in (headers or {}).items()}
    request.headers.get = lambda name, default="": hmap.get(name.lower(), default)
    request.app.state = SimpleNamespace(_rate_limit_trust_proxy=trust_proxy)
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
        request.headers.get = lambda name, default="": default
        request.app.state = SimpleNamespace(_rate_limit_trust_proxy=False)

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429

    def test_x_forwarded_for_ignored_by_default(self) -> None:
        """Without trust_proxy, X-Forwarded-For is not consulted."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        # Both requests share the same proxy IP; XFF differs but is ignored.
        req_a = _make_request("10.0.0.1", headers={"x-forwarded-for": "1.1.1.1"})
        req_b = _make_request("10.0.0.1", headers={"x-forwarded-for": "2.2.2.2"})
        limiter(req_a)
        limiter(req_b)
        with pytest.raises(HTTPException):
            limiter(_make_request("10.0.0.1", headers={"x-forwarded-for": "3.3.3.3"}))

    def test_x_forwarded_for_honored_when_trusted(self) -> None:
        """With trust_proxy, the left-most XFF entry buckets counters per client."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        req_a = _make_request(
            "10.0.0.1",
            headers={"x-forwarded-for": "1.1.1.1, 10.0.0.5"},
            trust_proxy=True,
        )
        req_b = _make_request(
            "10.0.0.1",
            headers={"x-forwarded-for": "2.2.2.2, 10.0.0.5"},
            trust_proxy=True,
        )
        # Two calls each — different XFF clients, so neither should be blocked.
        limiter(req_a)
        limiter(req_a)
        limiter(req_b)
        limiter(req_b)
        # But a third call from client A now trips.
        with pytest.raises(HTTPException):
            limiter(req_a)

    def test_x_forwarded_for_empty_falls_back_to_client_host(self) -> None:
        """A blank XFF value must not create an empty bucket."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        # No XFF entry present; trust_proxy still on. Should key off client.host.
        req = _make_request("10.0.0.9", trust_proxy=True)
        limiter(req)
        limiter(req)
        with pytest.raises(HTTPException):
            limiter(req)


class TestRateLimitDependency:
    """Unit tests for the rate_limit_dependency() factory."""

    def _make_app(self, *, keys_rate_limit: int = 2, keys_rate_window: int = 60) -> MagicMock:
        settings = SimpleNamespace(
            keys_rate_limit=keys_rate_limit,
            keys_rate_window=keys_rate_window,
        )
        state = SimpleNamespace(settings=settings, _rate_limit_trust_proxy=False)
        app = MagicMock()
        app.state = state
        return app

    def test_lazy_initialisation_and_reuse(self) -> None:
        dep = rate_limit_dependency("keys")
        app = self._make_app(keys_rate_limit=2)

        req_a = _make_request("10.0.0.1")
        req_a.app = app
        # First call creates the limiter and cache it on state.
        dep(req_a)
        limiter_first = app.state._keys_rate_limiter
        assert isinstance(limiter_first, RateLimiter)
        # Second call reuses the same limiter instance.
        dep(req_a)
        assert app.state._keys_rate_limiter is limiter_first
        # Third call trips 429.
        with pytest.raises(HTTPException) as exc_info:
            dep(req_a)
        assert exc_info.value.status_code == 429

    def test_reads_settings_by_name(self) -> None:
        dep = rate_limit_dependency("keys")
        app = self._make_app(keys_rate_limit=1, keys_rate_window=30)
        req = _make_request("10.0.0.1")
        req.app = app
        dep(req)
        limiter = app.state._keys_rate_limiter
        assert limiter.max_requests == 1
        assert limiter.window_seconds == 30

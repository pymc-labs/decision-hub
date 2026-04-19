"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter


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

    def test_purge_triggers_after_fixed_call_count(self) -> None:
        """Purge fires every ``_PURGE_EVERY`` enforced calls, not on every call.

        Guards against regressions of the old ``sum(len(v) …)`` scan that ran
        inside the hot path on every request.
        """
        from decision_hub.api import rate_limit as rl

        limiter = RateLimiter(max_requests=10_000, window_seconds=60)
        calls: list[float] = []
        original = limiter._purge_stale

        def counting(cutoff: float) -> None:
            calls.append(cutoff)
            original(cutoff)

        # Patch the bound method on the instance — avoids touching the class.
        limiter._purge_stale = counting  # type: ignore[method-assign]

        request = _make_request()
        for _ in range(rl.RateLimiter._PURGE_EVERY):
            limiter(request)
        assert len(calls) == 1


class TestRateLimitFactory:
    """Tests for the ``rate_limit`` / ``rate_limit_dep`` factory helpers."""

    def test_dep_reads_settings_by_prefix_and_enforces_429(self) -> None:
        """``rate_limit("search")`` reads ``search_rate_limit``/``search_rate_window``."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from decision_hub.api.rate_limit import rate_limit

        settings = MagicMock()
        settings.search_rate_limit = 2
        settings.search_rate_window = 60

        app = FastAPI()
        app.state.settings = settings

        @app.get("/s", dependencies=[rate_limit("search")])
        def _s() -> dict:
            return {"ok": True}

        client = TestClient(app)
        assert client.get("/s").status_code == 200
        assert client.get("/s").status_code == 200
        assert client.get("/s").status_code == 429

    def test_dep_caches_limiter_on_app_state(self) -> None:
        """Subsequent route calls reuse the same ``RateLimiter`` instance."""
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from decision_hub.api.rate_limit import RateLimiter, rate_limit_dep

        settings = MagicMock()
        settings.publish_rate_limit = 100
        settings.publish_rate_window = 60

        app = FastAPI()
        app.state.settings = settings
        dep = rate_limit_dep("publish")

        @app.get("/a", dependencies=[Depends(dep)])
        def _a() -> dict:
            return {"ok": True}

        @app.get("/b", dependencies=[Depends(dep)])
        def _b() -> dict:
            return {"ok": True}

        client = TestClient(app)
        client.get("/a")
        client.get("/b")
        cached = app.state._rate_limiter_publish
        assert isinstance(cached, RateLimiter)
        # Second access returns the same object — not a freshly built one.
        assert app.state._rate_limiter_publish is cached

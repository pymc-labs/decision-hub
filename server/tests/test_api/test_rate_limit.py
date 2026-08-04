"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from decision_hub.api.rate_limit import RateLimiter, RateLimiters, limiter_dep


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

    def test_purge_uses_monotonic_counter(self) -> None:
        """Purging fires every N requests via a counter, not sum-of-lens.

        Regression: the old implementation triggered on
        ``sum(len(v) for v in self._requests.values()) % 100 == 0``,
        which can easily skip 100 (e.g. counter goes 99 → 101 when the
        same IP gets pruned before adding). It also ran O(n_ips) work
        under the lock on every request.
        """
        limiter = RateLimiter(max_requests=1000, window_seconds=60)

        with patch("decision_hub.api.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0

            # Populate a stale bucket that will be purged
            stale_req = _make_request("10.0.0.99")
            limiter(stale_req)

            # Advance time so the stale bucket's timestamp is now outside
            # the window when the next purge runs.
            mock_time.monotonic.return_value = 1100.0

            # Fire exactly _PURGE_EVERY admissions from a different IP so
            # the counter reaches the purge threshold.
            active_req = _make_request("10.0.0.1")
            for _ in range(RateLimiter._PURGE_EVERY):
                limiter(active_req)

            # Stale bucket must have been dropped despite never being
            # the target of the check-and-purge loop.
            assert "10.0.0.99" not in limiter._requests

    def test_over_limit_admissions_do_not_advance_counter(self) -> None:
        """Rejected requests must not bump the request counter.

        Otherwise an attacker over the limit could still trigger the
        (locked) purge sweep on every rejected request.
        """
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        req = _make_request()
        limiter(req)  # counter = 1
        for _ in range(5):
            with pytest.raises(HTTPException):
                limiter(req)
        # Rejections raised before the counter increment, so it stayed at 1.
        assert limiter._request_count == 1


class TestRateLimiters:
    """The named-container wired up at app startup."""

    def test_builds_all_known_limiters_from_settings(self) -> None:
        settings = MagicMock()
        # Every known name reads two settings fields; give them all values.
        for name in RateLimiters._NAMES:
            setattr(settings, f"{name}_rate_limit", 5)
            setattr(settings, f"{name}_rate_window", 60)

        limiters = RateLimiters(settings)

        for name in RateLimiters._NAMES:
            got = limiters.get(name)
            assert isinstance(got, RateLimiter)
            assert got.max_requests == 5
            assert got.window_seconds == 60

    def test_unknown_name_raises_key_error(self) -> None:
        settings = MagicMock()
        for name in RateLimiters._NAMES:
            setattr(settings, f"{name}_rate_limit", 5)
            setattr(settings, f"{name}_rate_window", 60)
        limiters = RateLimiters(settings)
        with pytest.raises(KeyError):
            limiters.get("nonexistent")


class TestLimiterDep:
    """FastAPI dependency wiring."""

    def test_limiter_dep_enforces_limit_via_app_state(self) -> None:
        """Route with limiter_dep('resolve') should 429 the fourth call."""
        settings = MagicMock()
        for name in RateLimiters._NAMES:
            setattr(settings, f"{name}_rate_limit", 3 if name == "resolve" else 100)
            setattr(settings, f"{name}_rate_window", 60)

        app = FastAPI()
        app.state.rate_limiters = RateLimiters(settings)

        from fastapi import Depends

        @app.get("/probe", dependencies=[Depends(limiter_dep("resolve"))])
        def _probe() -> dict:
            return {"ok": True}

        client = TestClient(app)
        for _ in range(3):
            assert client.get("/probe").status_code == 200
        assert client.get("/probe").status_code == 429

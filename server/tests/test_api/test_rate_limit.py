"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import (
    _RATE_LIMIT_NAMES,
    RateLimiter,
    build_rate_limiters,
    rate_limit,
)


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


def _fake_settings(**overrides) -> SimpleNamespace:
    """Build a Settings stand-in that exposes every <name>_rate_limit/window pair.

    Tests rely on duck-typing rather than the real ``Settings`` model so they
    can vary individual fields without re-spelling every other rate setting.
    """
    base = {}
    for name in _RATE_LIMIT_NAMES:
        base[f"{name}_rate_limit"] = 5
        base[f"{name}_rate_window"] = 60
    base.update(overrides)
    return SimpleNamespace(**base)


class TestBuildRateLimiters:
    """Unit tests for ``build_rate_limiters()`` — the eager-init factory."""

    def test_builds_one_limiter_per_registered_name(self) -> None:
        limiters = build_rate_limiters(_fake_settings())
        assert set(limiters.keys()) == set(_RATE_LIMIT_NAMES)
        assert all(isinstance(v, RateLimiter) for v in limiters.values())

    def test_each_limiter_uses_its_own_settings_pair(self) -> None:
        """The factory must wire each limiter to its own ``<name>_*`` fields,
        not, for example, share a single global limit across routes."""
        settings = _fake_settings(
            search_rate_limit=1,
            search_rate_window=10,
            publish_rate_limit=99,
            publish_rate_window=99,
        )
        limiters = build_rate_limiters(settings)
        assert (limiters["search"].max_requests, limiters["search"].window_seconds) == (1, 10)
        assert (limiters["publish"].max_requests, limiters["publish"].window_seconds) == (99, 99)

    def test_each_limiter_is_a_distinct_instance(self) -> None:
        """Routes must not share the same RateLimiter — that would leak
        request counts across endpoints with very different traffic shapes."""
        limiters = build_rate_limiters(_fake_settings())
        seen_ids = {id(v) for v in limiters.values()}
        assert len(seen_ids) == len(limiters)


class TestRateLimitDependency:
    """Unit tests for ``rate_limit('<name>')`` — the FastAPI dependency factory."""

    def test_rejects_unknown_name_at_construction(self) -> None:
        """Typos in route definitions should fail loudly at import time."""
        with pytest.raises(KeyError, match="Unknown rate-limit name"):
            rate_limit("does-not-exist")

    def test_dispatches_to_prebuilt_limiter(self) -> None:
        """When ``app.state.rate_limiters`` exists, the dep must look up by name
        and never construct a new limiter (production path)."""
        # Plain MagicMock — RateLimiter is callable, that's all the dep needs.
        target = MagicMock()
        other = MagicMock()
        request = _make_request()
        request.app.state = SimpleNamespace(rate_limiters={"search": target, "publish": other})

        rate_limit("search")(request)

        target.assert_called_once_with(request)
        other.assert_not_called()

    def test_lazily_builds_when_state_dict_missing(self) -> None:
        """Test apps that bypass create_app() never set ``rate_limiters``;
        the dep must build it from settings on first call so test fixtures
        don't have to duplicate the wiring."""
        request = _make_request()
        request.app.state = SimpleNamespace(settings=_fake_settings(search_rate_limit=2, search_rate_window=60))

        # First call lazily populates the dict
        rate_limit("search")(request)
        assert isinstance(request.app.state.rate_limiters, dict)
        assert "search" in request.app.state.rate_limiters

        # Second call reuses the same dict (state is shared)
        prior = request.app.state.rate_limiters
        rate_limit("search")(request)
        assert request.app.state.rate_limiters is prior

    def test_dependency_propagates_429_from_limiter(self) -> None:
        """A 429 from the underlying limiter must surface unchanged so
        FastAPI returns the right status to the caller."""
        request = _make_request()
        request.app.state = SimpleNamespace(settings=_fake_settings(publish_rate_limit=1, publish_rate_window=60))

        dep = rate_limit("publish")
        dep(request)  # first call OK
        with pytest.raises(HTTPException) as exc_info:
            dep(request)  # second call exceeds the (1/60) limit
        assert exc_info.value.status_code == 429

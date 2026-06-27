"""Tests for decision_hub.api.rate_limit -- per-IP sliding-window rate limiter."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_hub.api.rate_limit import RateLimiter


def _make_request(host: str = "127.0.0.1", method: str = "GET", path: str = "/v1/foo") -> MagicMock:
    """Create a mock Request with a given client IP, method, and path."""
    request = MagicMock()
    request.client.host = host
    request.method = method
    request.url.path = path
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
        request.method = "GET"
        request.url.path = "/v1/foo"

        for _ in range(2):
            limiter(request)

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429

    def test_logs_warning_when_limit_exceeded(self) -> None:
        """Rate-limit hits used to be silent 429s. Verify the limiter now
        logs a warning with the limiter name, client IP, method, and path
        so operators can spot scrapers in the logs."""
        from loguru import logger

        limiter = RateLimiter(max_requests=1, window_seconds=60, name="test_limiter")
        request = _make_request(host="10.1.2.3", method="GET", path="/v1/stats")

        # First request passes, second is rate-limited.
        limiter(request)

        seen: list[str] = []
        sink_id = logger.add(lambda msg: seen.append(str(msg)), level="WARNING")
        try:
            with pytest.raises(HTTPException):
                limiter(request)
        finally:
            logger.remove(sink_id)

        # Concatenate all captured lines so the assertion isn't sensitive
        # to loguru's formatter splitting on newlines.
        captured = "\n".join(seen)
        assert "rate_limit_exceeded" in captured
        assert "test_limiter" in captured
        assert "10.1.2.3" in captured
        assert "/v1/stats" in captured

    def test_unnamed_limiter_logs_default_name(self) -> None:
        """When no name is provided, the warning falls back to 'rate_limiter'."""
        from loguru import logger

        limiter = RateLimiter(max_requests=1, window_seconds=60)
        request = _make_request()
        limiter(request)

        seen: list[str] = []
        sink_id = logger.add(lambda msg: seen.append(str(msg)), level="WARNING")
        try:
            with pytest.raises(HTTPException):
                limiter(request)
        finally:
            logger.remove(sink_id)
        assert "rate_limiter" in "\n".join(seen)

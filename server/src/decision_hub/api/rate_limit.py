"""In-memory sliding-window rate limiter for FastAPI dependencies."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import HTTPException, Request


class RateLimiter:
    """Per-IP sliding-window rate limiter.

    Tracks request timestamps per client IP in memory. Works well for
    Modal serverless containers where each container handles its own
    traffic. Not shared across containers -- that's fine for preventing
    a single client from hammering a single container.

    Thread-safe: FastAPI runs sync dependencies in a threadpool, so
    concurrent access to shared state is guarded by a lock.

    Usage as a FastAPI dependency::

        limiter = RateLimiter(max_requests=10, window_seconds=60)

        @router.get("/search", dependencies=[Depends(limiter)])
        def search(...): ...
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        # Drive stale-IP purging from monotonic time, not from a request
        # counter. The previous "every Nth request" trigger could be
        # skipped entirely when rate-limit drops shifted the running
        # total past the modulo boundary, allowing the dict to grow
        # unboundedly under bursty fan-in traffic. A time-based trigger
        # is both cheaper to reason about and bounded by window_seconds.
        self._next_purge_at: float = time.monotonic() + window_seconds

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            # Prune expired timestamps for this key
            timestamps = self._requests[key]
            self._requests[key] = [t for t in timestamps if t > cutoff]

            if len(self._requests[key]) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests per {self.window_seconds}s). Try again shortly."
                    ),
                )

            self._requests[key].append(now)

            # Periodically purge IPs that haven't been seen this window.
            # Time-based (not counter-based) so it fires reliably even
            # when traffic comes from many short-lived IPs that each
            # make a single request.
            if now >= self._next_purge_at:
                self._purge_stale(cutoff)
                self._next_purge_at = now + self.window_seconds

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def make_rate_limit_dependency(
    name: str,
    *,
    limit_attr: str,
    window_attr: str,
) -> Callable[[Request], None]:
    """Build a FastAPI dependency that lazily creates and applies a RateLimiter.

    The limiter is stored on ``request.app.state`` under the attribute
    ``_<name>_rate_limiter`` so it is shared across requests within a
    container while still being scoped per-app. Settings are read from
    ``request.app.state.settings`` using the two attribute names
    provided.

    This collapses what used to be a 10-line function per endpoint into
    a single call site::

        _enforce_search_rate_limit = make_rate_limit_dependency(
            "search",
            limit_attr="search_rate_limit",
            window_attr="search_rate_window",
        )

    Args:
        name: Identifier used for the cached limiter attribute on app
            state. Must be unique across the application.
        limit_attr: Name of the integer ``max_requests`` attribute on
            ``Settings``.
        window_attr: Name of the integer ``window_seconds`` attribute on
            ``Settings``.

    Returns:
        A FastAPI dependency callable that enforces the rate limit.
    """
    state_attr = f"_{name}_rate_limiter"

    def _dependency(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, state_attr, None)
        if limiter is None:
            settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, limit_attr),
                window_seconds=getattr(settings, window_attr),
            )
            setattr(state, state_attr, limiter)
        limiter(request)

    _dependency.__name__ = f"_enforce_{name}_rate_limit"
    _dependency.__doc__ = f"Rate-limit dependency for the '{name}' endpoint group."
    return _dependency

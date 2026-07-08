"""In-memory sliding-window rate limiter for FastAPI dependencies."""

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

    # Purge stale IPs every N successful admissions.  Amortises the O(n)
    # scan across many requests while keeping memory growth bounded.
    _PURGE_INTERVAL = 100

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        # Count of admissions since the last purge.  Cheap O(1) counter
        # instead of the previous O(n) sum() over every tracked IP.
        self._admissions_since_purge = 0

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

            # Periodically purge stale IPs to bound memory growth.
            self._admissions_since_purge += 1
            if self._admissions_since_purge >= self._PURGE_INTERVAL:
                self._purge_stale(cutoff)
                self._admissions_since_purge = 0

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def make_rate_limit_dep(name: str, limit_attr: str, window_attr: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency that lazily initialises a per-route rate limiter.

    The pattern of "check ``app.state`` for a cached limiter, otherwise
    construct one from a pair of settings" was previously duplicated in
    nine ``_enforce_*_rate_limit`` helpers across the routers.  This
    factory captures the pattern in one place.

    Args:
        name: Distinguishing suffix for the ``app.state`` cache attribute
            (e.g. ``"search"``, ``"publish"``, ``"list_skills"``).  Two
            dependencies with the same *name* share the same limiter
            instance, so pick a unique value per route family.
        limit_attr: Name of the ``Settings`` field holding the max-request
            count for the window (e.g. ``"search_rate_limit"``).
        window_attr: Name of the ``Settings`` field holding the window in
            seconds (e.g. ``"search_rate_window"``).

    Returns:
        A callable suitable for use with ``fastapi.Depends``.
    """
    cache_attr = f"_{name}_rate_limiter"

    def dependency(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, cache_attr, None)
        if limiter is None:
            settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, limit_attr),
                window_seconds=getattr(settings, window_attr),
            )
            setattr(state, cache_attr, limiter)
        limiter(request)

    dependency.__name__ = f"enforce_{name}_rate_limit"
    dependency.__qualname__ = dependency.__name__
    return dependency

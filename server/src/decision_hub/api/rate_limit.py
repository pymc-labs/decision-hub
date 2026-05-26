"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import HTTPException, Request

# Purge stale per-IP buckets every N successful checks. Bounded so that
# the limiter never holds more than ~N distinct idle IPs at the cost of
# one O(distinct-IPs) sweep per N requests.
_PURGE_EVERY_N_REQUESTS = 100


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
        # Counter of successful checks since last purge. Used to drive
        # periodic eviction of idle IPs in O(1) amortised time per call.
        self._checks_since_purge = 0

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
            # Driven by an explicit request counter rather than the sum of
            # all in-flight timestamps (which would never hit the modulo
            # boundary at steady-state).
            self._checks_since_purge += 1
            if self._checks_since_purge >= _PURGE_EVERY_N_REQUESTS:
                self._purge_stale(cutoff)
                self._checks_since_purge = 0

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def make_rate_limit_dep(name: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency that lazily creates a per-app RateLimiter.

    Reads ``{name}_rate_limit`` and ``{name}_rate_window`` from app settings
    on first call and caches the limiter under ``app.state.rate_limiters[name]``.

    Args:
        name: Settings prefix for this limiter (e.g. ``"publish"`` reads
            ``settings.publish_rate_limit`` / ``settings.publish_rate_window``).

    Returns:
        A FastAPI dependency callable suitable for ``Depends(...)``.
    """
    max_attr = f"{name}_rate_limit"
    window_attr = f"{name}_rate_window"

    def dep(request: Request) -> None:
        state = request.app.state
        limiters: dict[str, RateLimiter]
        # Lazily initialise the per-app limiter registry. The lookup is
        # already inside the request hot path, so a small dict is fine.
        if not hasattr(state, "rate_limiters"):
            state.rate_limiters = {}
        limiters = state.rate_limiters
        limiter = limiters.get(name)
        if limiter is None:
            settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, max_attr),
                window_seconds=getattr(settings, window_attr),
            )
            limiters[name] = limiter
        limiter(request)

    dep.__name__ = f"enforce_{name}_rate_limit"
    dep.__qualname__ = dep.__name__
    return dep

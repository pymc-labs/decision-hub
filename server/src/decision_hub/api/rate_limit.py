"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from typing import Any

from fastapi import HTTPException, Request

# Periodically scan for and evict stale IPs so memory growth is bounded.
# Triggered every Nth call rather than on every call to keep the hot path
# cheap. Counter-based so the cadence is independent of traffic shape.
_PURGE_EVERY_N_CALLS = 1024


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
        # Per-instance call counter drives periodic stale-IP eviction.
        # Earlier this used `total = sum(len(v) for v in requests.values()) % 100`,
        # which rarely hit zero once timestamps were pruned each call and made
        # the purge cadence depend on request rate per IP. A plain counter
        # purges reliably every N calls regardless of traffic shape.
        self._call_count = 0

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

            self._call_count += 1
            if self._call_count >= _PURGE_EVERY_N_CALLS:
                self._call_count = 0
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def get_or_create_limiter(
    app_state: Any,
    attr_name: str,
    *,
    max_requests: int,
    window_seconds: int,
) -> RateLimiter:
    """Return a RateLimiter from app.state, lazily creating it on first call.

    Centralises the "check attribute, build from settings, stash on state"
    pattern that was previously duplicated across every public route module.
    The first caller pays the construction cost; every subsequent caller
    reuses the same limiter instance.
    """
    limiter = getattr(app_state, attr_name, None)
    if limiter is None:
        limiter = RateLimiter(max_requests=max_requests, window_seconds=window_seconds)
        setattr(app_state, attr_name, limiter)
    return limiter

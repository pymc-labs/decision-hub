"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict

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

    # Run the stale-IP purge every N admitted requests. Cheap counter
    # avoids the O(n) `sum(len(v) for ...)` that the previous
    # implementation ran on every call.
    _PURGE_EVERY = 100

    # Hard ceiling on tracked IPs. A botnet of rotating source IPs would
    # otherwise force unbounded growth between purges. When breached we
    # purge eagerly; if that doesn't free space we drop the request with
    # 429 instead of growing without bound.
    _MAX_TRACKED_KEYS = 10_000

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._calls_since_purge = 0

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
            self._calls_since_purge += 1

            # Periodic background purge keeps the dict from growing slowly
            # under steady traffic.
            if self._calls_since_purge >= self._PURGE_EVERY:
                self._purge_stale(cutoff)
                self._calls_since_purge = 0

            # Hard ceiling: under a flood of unique IPs the periodic purge
            # is too lazy. Force a purge once we cross the cap and, if the
            # caller is itself a brand-new IP that pushed us over, reject.
            if len(self._requests) > self._MAX_TRACKED_KEYS:
                self._purge_stale(cutoff)
                self._calls_since_purge = 0
                if len(self._requests) > self._MAX_TRACKED_KEYS:
                    raise HTTPException(
                        status_code=429,
                        detail="Rate limiter saturated. Try again shortly.",
                    )

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]

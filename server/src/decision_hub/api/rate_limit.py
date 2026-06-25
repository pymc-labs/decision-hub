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

    _PURGE_EVERY = 100

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        # Monotonic counter — drives the periodic purge. Previously we summed
        # all timestamps in `_requests` and checked `total % 100 == 0`, but
        # `total` recomputed each call almost never landed exactly on a
        # multiple of 100, so `_purge_stale` effectively never ran and IPs
        # accumulated for the lifetime of the (long-lived) Modal container.
        self._calls_since_purge = 0

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            # Prune expired timestamps for this key
            timestamps = self._requests[key]
            timestamps = [t for t in timestamps if t > cutoff]
            self._requests[key] = timestamps

            if len(timestamps) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests per {self.window_seconds}s). Try again shortly."
                    ),
                )

            timestamps.append(now)

            # Bound memory growth by purging IPs whose entries are all older
            # than the window once every _PURGE_EVERY calls.
            self._calls_since_purge += 1
            if self._calls_since_purge >= self._PURGE_EVERY:
                self._calls_since_purge = 0
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]

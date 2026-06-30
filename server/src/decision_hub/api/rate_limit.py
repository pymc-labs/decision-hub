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

    # Hard ceiling on tracked IPs. A slow-and-low attack from many unique
    # source addresses (or IPv6, where each /64 has 2**64 addresses) could
    # otherwise grow _requests without bound between the periodic purges.
    # Tuned to comfortably cover realistic traffic per container while
    # capping worst-case RSS at a few MB.
    _MAX_TRACKED_KEYS = 10_000

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

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

            # Bound memory: if we ever exceed the cap (which the "every 100
            # requests" purge can fail to prevent under high-cardinality IP
            # spray), purge stale keys immediately, and then evict the
            # oldest-active keys if we're still over.
            if len(self._requests) > self._MAX_TRACKED_KEYS:
                self._purge_stale(cutoff)
                if len(self._requests) > self._MAX_TRACKED_KEYS:
                    self._evict_oldest(self._MAX_TRACKED_KEYS // 10)
            else:
                # Cheap periodic purge under normal load.
                total = sum(len(v) for v in self._requests.values())
                if total % 100 == 0:
                    self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]

    def _evict_oldest(self, count: int) -> None:
        """Evict *count* keys whose most-recent request is oldest.

        Used only as a backstop when the tracked-key cap is exceeded after
        a normal purge. Caller must hold self._lock.
        """
        ordered = sorted(self._requests.items(), key=lambda kv: kv[1][-1] if kv[1] else 0)
        for k, _ in ordered[:count]:
            del self._requests[k]

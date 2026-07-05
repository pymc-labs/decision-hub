"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request

# Refresh the stale-IP purge at most once every N seconds. Prevents the
# hot path from computing sum(len(...)) under the lock on every request.
_PURGE_INTERVAL_SECONDS = 60.0


def _client_ip(request: Request) -> str:
    """Extract the caller's IP, honoring proxy headers.

    Modal (and most reverse proxies) terminate TLS at the ingress and put
    the real client IP in ``X-Forwarded-For`` (comma-separated, left-most
    is the original client). Falling back to ``request.client.host`` would
    make every user share one bucket per container — effectively disabling
    the limiter.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # First entry is the original client; subsequent are proxy hops.
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


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
        self._last_purge: float = 0.0

    def __call__(self, request: Request) -> None:
        key = _client_ip(request)
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

            # Purge stale IPs on a wall-clock cadence. Cheaper and more
            # predictable than the old modulo-of-total scheme, which
            # both scanned every bucket under lock and skipped 100 under
            # contention (so purges rarely ran).
            if now - self._last_purge > _PURGE_INTERVAL_SECONDS:
                self._purge_stale(cutoff)
                self._last_purge = now

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]

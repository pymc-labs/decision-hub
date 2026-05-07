"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request

from decision_hub.api.client_ip import client_ip


class RateLimiter:
    """Per-IP sliding-window rate limiter.

    Tracks request timestamps per client IP in memory. Works well for
    Modal serverless containers where each container handles its own
    traffic. Not shared across containers -- that's fine for preventing
    a single client from hammering a single container.

    Thread-safe: FastAPI runs sync dependencies in a threadpool, so
    concurrent access to shared state is guarded by a lock.

    The client IP is resolved via :func:`client_ip`, which honors a trusted
    forwarded header when ``Settings.trusted_proxy`` is enabled. Without that
    setting every request behind a load balancer (e.g. Modal) would share the
    LB's source IP and the per-IP limit would collapse into a global limit.

    Usage as a FastAPI dependency::

        limiter = RateLimiter(max_requests=10, window_seconds=60)

        @router.get("/search", dependencies=[Depends(limiter)])
        def search(...): ...
    """

    # Run periodic cleanup at most this often. Cheap to check; bounds memory
    # growth even if a malicious client cycles through many IPs.
    _PURGE_INTERVAL_SECONDS = 60.0

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._last_purge_at = 0.0

    def __call__(self, request: Request) -> None:
        key = client_ip(request)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._requests[key]
            timestamps = [t for t in timestamps if t > cutoff]
            self._requests[key] = timestamps

            if len(timestamps) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests per "
                        f"{self.window_seconds}s). Try again shortly."
                    ),
                )

            timestamps.append(now)

            if now - self._last_purge_at >= self._PURGE_INTERVAL_SECONDS:
                self._purge_stale(cutoff)
                self._last_purge_at = now

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]

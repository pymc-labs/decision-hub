"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request
from loguru import logger


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

    When the limit is hit the limiter logs a warning carrying the IP,
    HTTP method, and path so operators can spot scrapers and bursty
    clients in the logs. The HTTPException response stays generic.
    """

    def __init__(self, max_requests: int, window_seconds: int, *, name: str | None = None) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # Optional human-readable label that appears in the warning log
        # when a request is rejected. Defaults to "rate_limiter".
        self.name = name or "rate_limiter"
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
                # Observability: rate-limit hits used to be silent 429s
                # which made it hard to spot abuse in practice. Log at
                # warning level with greppable identifiers (limiter name,
                # client IP, method, path) per CLAUDE.md logging rules.
                logger.warning(
                    "rate_limit_exceeded limiter={} ip={} method={} path={} limit={}/{}s",
                    self.name,
                    key,
                    request.method,
                    request.url.path,
                    self.max_requests,
                    self.window_seconds,
                )
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests per {self.window_seconds}s). Try again shortly."
                    ),
                )

            self._requests[key].append(now)

            # Periodically purge stale IPs to bound memory growth.
            # Check every 100 requests (cheap modulo on list length).
            total = sum(len(v) for v in self._requests.values())
            if total % 100 == 0:
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]

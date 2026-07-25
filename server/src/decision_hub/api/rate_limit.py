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

    Client-IP resolution: falls back to ``X-Forwarded-For`` (first hop)
    when set. Modal fronts the app with a proxy, so ``request.client.host``
    is the proxy IP -- without the header fallback every user would share
    a single bucket, defeating the limiter. The header can be spoofed by
    an attacker who talks directly to the container, but Modal's frontend
    strips inbound XFF and re-adds its own trusted value.

    Usage as a FastAPI dependency::

        limiter = RateLimiter(max_requests=10, window_seconds=60)

        @router.get("/search", dependencies=[Depends(limiter)])
        def search(...): ...
    """

    # Purge stale IPs every N requests. Keeps the map bounded under scan
    # attacks (each spoofed IP creates a bucket) without paying for a scan
    # of every bucket on every request.
    _PURGE_INTERVAL = 100

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        # O(1) trigger for periodic pruning. The previous implementation
        # summed len() across every IP list on every request, which turned
        # the hot path into an O(N-IPs) scan the moment traffic picked up.
        self._request_count = 0

    def __call__(self, request: Request) -> None:
        key = _client_key(request)
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

            self._request_count += 1
            if self._request_count % self._PURGE_INTERVAL == 0:
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def _client_key(request: Request) -> str:
    """Resolve the rate-limit key for the request.

    Prefers the first entry of ``X-Forwarded-For`` when present, so requests
    behind a reverse proxy don't all share a single bucket. Falls back to
    ``request.client.host`` (direct socket peer) and finally to ``"unknown"``.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # XFF is a comma-separated list "<real>, <proxy1>, <proxy2>"; the
        # first entry is the original client. Strip surrounding whitespace.
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    if request.client is not None:
        return request.client.host
    return "unknown"

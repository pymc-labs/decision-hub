"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request
from starlette.datastructures import State


class RateLimiter:
    """Per-IP sliding-window rate limiter.

    Tracks request timestamps per client IP in memory. Works well for
    Modal serverless containers where each container handles its own
    traffic. Not shared across containers -- that's fine for preventing
    a single client from hammering a single container.

    Thread-safe: FastAPI runs sync dependencies in a threadpool, so
    concurrent access to shared state is guarded by a lock.

    Client-IP resolution honours ``X-Forwarded-For`` when the request is
    coming from a trusted upstream (Modal terminates TLS and forwards
    the original IP in this header). Without this, every request looks
    like it came from the proxy address and one heavy caller starves
    everyone else on the same container.

    Usage as a FastAPI dependency::

        limiter = RateLimiter(max_requests=10, window_seconds=60)

        @router.get("/search", dependencies=[Depends(limiter)])
        def search(...): ...
    """

    # Purge stale IP buckets every N accepted requests. Bounded work per
    # admission; O(unique-ips) at trigger time, not O(total-entries).
    _PURGE_INTERVAL = 100

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._admissions_since_purge = 0

    def __call__(self, request: Request) -> None:
        key = _client_key(request)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            # Prune expired timestamps for this key
            timestamps = self._requests[key]
            fresh = [t for t in timestamps if t > cutoff]
            self._requests[key] = fresh

            if len(fresh) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests per {self.window_seconds}s). Try again shortly."
                    ),
                )

            fresh.append(now)

            # Periodically purge stale IPs to bound memory growth.
            # An accumulator avoids the O(total-entries) sum() the previous
            # implementation ran on every admission.
            self._admissions_since_purge += 1
            if self._admissions_since_purge >= self._PURGE_INTERVAL:
                self._admissions_since_purge = 0
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def _client_key(request: Request) -> str:
    """Return a stable per-client key for rate limiting.

    Prefers the first entry of ``X-Forwarded-For`` (added by Modal /
    reverse proxies), then falls back to ``request.client.host``.
    Trusts the header because Modal's edge is the only ingress; behind a
    different topology this would need an explicit trusted-proxy list.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # First entry is the original client; subsequent entries are proxy hops.
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    if request.client:
        return request.client.host
    return "unknown"


# ---------------------------------------------------------------------------
# Lazy limiter registry (thread-safe)
# ---------------------------------------------------------------------------

# Guards concurrent lazy-init in _get_or_create_limiter. Without this,
# two concurrent requests to a fresh container both instantiate a new
# RateLimiter and the second setattr replaces the first — the accounting
# for whichever bucket lost the race is discarded. Attackers can time
# bursts against cold-starts to double their effective quota.
_INIT_LOCK = threading.Lock()


def get_or_create_limiter(
    state: State,
    name: str,
    max_requests: int,
    window_seconds: int,
) -> RateLimiter:
    """Return the RateLimiter stored on ``state`` under ``name``, creating it once.

    Thread-safe: guarded by a module-level lock so concurrent first-access
    doesn't produce two limiter instances (see comment on ``_INIT_LOCK``).
    """
    limiter = getattr(state, name, None)
    if limiter is not None:
        return limiter
    with _INIT_LOCK:
        # Re-check under the lock (double-checked locking) so we don't
        # replace a limiter another thread already created.
        limiter = getattr(state, name, None)
        if limiter is None:
            limiter = RateLimiter(
                max_requests=max_requests,
                window_seconds=window_seconds,
            )
            setattr(state, name, limiter)
        return limiter

"""In-memory sliding-window rate limiter for FastAPI dependencies."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request

# Purge stale-IP entries every this many *observed* requests. A plain
# integer counter is used so the cadence is deterministic and independent
# of workload distribution (a modulo over a whole-dict sum, as previously,
# is neither periodic nor cheap under load).
_PURGE_EVERY_N_REQUESTS = 500


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
        # Per-key deque so stale timestamps can be popped from the head
        # without allocating a fresh list on every request. Amortised O(1)
        # under steady-state traffic.
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        # Deterministic purge cadence — no dict-wide sum on the hot path.
        self._request_counter = 0

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._requests[key]
            # Drop expired timestamps in place. Deque is ordered by insertion
            # (which is monotonic), so popping from the head is enough.
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests per {self.window_seconds}s). Try again shortly."
                    ),
                )

            timestamps.append(now)

            self._request_counter += 1
            if self._request_counter >= _PURGE_EVERY_N_REQUESTS:
                self._request_counter = 0
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] <= cutoff]
        for k in stale:
            del self._requests[k]


def make_rate_limit_dependency(name: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency that enforces the ``<name>`` rate limit.

    The returned callable looks up ``settings.<name>_rate_limit`` and
    ``settings.<name>_rate_window`` from app state, lazily creating a
    ``RateLimiter`` stored at ``app.state._<name>_rate_limiter`` on first
    use, and delegates enforcement to it.

    Consolidates the identical "if not hasattr(state, ...): state.X =
    RateLimiter(...)" boilerplate that previously appeared once per
    protected endpoint in the API layer.

    The one-time lazy init is intentionally lock-free — under the tiny race
    window where two startup requests both create a limiter, the losing
    write is discarded and one request's timestamp is dropped. Acceptable
    for a soft limiter with a 60s+ window.
    """
    attr_name = f"_{name}_rate_limiter"
    max_requests_attr = f"{name}_rate_limit"
    window_seconds_attr = f"{name}_rate_window"

    def dep(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, attr_name, None)
        if limiter is None:
            settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, max_requests_attr),
                window_seconds=getattr(settings, window_seconds_attr),
            )
            setattr(state, attr_name, limiter)
        limiter(request)

    dep.__name__ = f"_enforce_{name}_rate_limit"
    return dep

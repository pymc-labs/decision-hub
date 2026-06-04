"""In-memory sliding-window rate limiter for FastAPI dependencies.

The limiter is per-IP and intentionally container-local: each Modal
container enforces its own quota, which is fine for stopping a single
client from hammering a single container.  If the deployment ever
auto-scales beyond one container, this protection becomes per-replica
— move to a shared store (Redis) at that point.
"""

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request

# How often the limiter scans its IP table to drop stale entries.
# A fraction of the window is a good balance: fresh enough to bound
# memory, sparse enough that the scan itself is amortised cheaply.
_PURGE_INTERVAL_FRACTION = 0.5


class RateLimiter:
    """Per-IP sliding-window rate limiter.

    Tracks request timestamps per client IP in memory.  Each IP has a
    bounded deque of recent monotonic timestamps; admission is decided
    by counting timestamps inside the window.

    Thread-safe: FastAPI runs sync dependencies in a threadpool, so the
    shared dict is guarded by a single lock.  All operations under the
    lock are O(k) where k is the number of expired timestamps for the
    current IP, not O(N-ips).

    Memory: stale IPs are evicted on a time-driven schedule rather than
    on a request counter, so a low-traffic instance still trims its
    table predictably and a high-traffic instance does not pay the
    sweep cost on every request.

    Usage as a FastAPI dependency::

        limiter = RateLimiter(max_requests=10, window_seconds=60)

        @router.get("/search", dependencies=[Depends(limiter)])
        def search(...): ...
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # Optional injected clock for unit tests.  When ``None`` we
        # resolve ``time.monotonic`` on every call so the existing
        # ``patch("decision_hub.api.rate_limit.time")`` test pattern
        # keeps working.
        self._clock = clock
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        # Drive eviction by elapsed time, not by request count.  The
        # previous ``total % 100 == 0`` heuristic fired on every cold
        # start (total = 0) and could fail to fire for hours under a
        # traffic shape that never hit an exact multiple.
        self._purge_interval = max(1.0, window_seconds * _PURGE_INTERVAL_FRACTION)
        self._next_purge_at = self._now() + self._purge_interval

    def _now(self) -> float:
        return self._clock() if self._clock is not None else time.monotonic()

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = self._now()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._requests[key]
            # popleft is O(1) and prunes only the expired front of the
            # deque -- the previous list comprehension rebuilt the
            # entire list on every request, which is O(n) per call.
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests per "
                        f"{self.window_seconds}s). Try again shortly."
                    ),
                )

            timestamps.append(now)

            if now >= self._next_purge_at:
                self._purge_stale(cutoff)
                self._next_purge_at = now + self._purge_interval

    def _purge_stale(self, cutoff: float) -> None:
        """Drop IPs whose most recent request is older than the window.

        Caller must hold ``self._lock``.  An empty deque also counts as
        stale -- it can be left behind by ``defaultdict`` access in a
        rejected admission.
        """
        stale = [k for k, ts in self._requests.items() if not ts or ts[-1] <= cutoff]
        for k in stale:
            del self._requests[k]


def get_or_create_limiter(
    state,
    name: str,
    max_requests: int,
    window_seconds: int,
) -> RateLimiter:
    """Lazily attach a named ``RateLimiter`` to ``app.state``.

    Each endpoint that needs rate limiting calls this from its own
    one-line ``Depends`` shim.  Keeping the limiter on ``app.state``
    means it lives for the lifetime of the container (one bucket per
    endpoint per container), which is the intended scope.

    The previous implementation duplicated a 12-line ``hasattr`` block
    per endpoint in every router module -- this helper collapses all of
    them into a single, tested function.
    """
    attr = f"_rate_limiter__{name}"
    limiter = getattr(state, attr, None)
    if limiter is None:
        limiter = RateLimiter(max_requests=max_requests, window_seconds=window_seconds)
        setattr(state, attr, limiter)
    return limiter

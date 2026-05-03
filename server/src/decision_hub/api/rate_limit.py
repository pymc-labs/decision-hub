"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request

from decision_hub.settings import Settings

# How often to scan the in-memory request map for stale per-IP entries.
# A counter increments per call and triggers a sweep every N requests so
# memory stays bounded even when individual IPs go quiet. Counter-based
# (not modulo on the live total) so the sweep is independent of state size.
_PURGE_EVERY_N_REQUESTS = 100


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
        # ``deque`` (vs list) lets us pop expired timestamps from the left
        # in amortised O(1) instead of rebuilding the list on every call.
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        # Counts every call; drives the periodic stale-IP sweep below.
        # Decoupling from ``len(self._requests)`` avoids a quirk where a
        # post-purge total of 0 satisfied ``total % 100 == 0`` and triggered
        # a sweep on every subsequent request.
        self._calls_since_purge = 0

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._requests[key]
            # popleft is O(1); deque is sorted by insertion (monotonic time).
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

            self._calls_since_purge += 1
            if self._calls_since_purge >= _PURGE_EVERY_N_REQUESTS:
                self._purge_stale(cutoff)
                self._calls_since_purge = 0

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] <= cutoff]
        for k in stale:
            del self._requests[k]


def make_rate_limiter_dep(
    state_attr: str,
    limit_attr: str,
    window_attr: str,
) -> Callable[[Request], None]:
    """Build a FastAPI dependency that lazily wires up a per-route ``RateLimiter``.

    The same one-shot lazy-init pattern was previously copy-pasted nine times
    across the route modules; this factory replaces all of them.

    Args:
        state_attr: Name of the attribute on ``app.state`` used to cache the
            ``RateLimiter`` instance for this dependency. Each route must use
            a unique attribute so independent routes get independent buckets.
        limit_attr: ``Settings`` attribute holding the max-requests value.
        window_attr: ``Settings`` attribute holding the window-seconds value.

    Returns:
        A callable suitable for ``Depends(...)``.
    """

    def _enforce(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, state_attr, None)
        if limiter is None:
            settings: Settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, limit_attr),
                window_seconds=getattr(settings, window_attr),
            )
            setattr(state, state_attr, limiter)
        limiter(request)

    # Helpful on tracebacks; FastAPI also keys schema by callable identity.
    _enforce.__name__ = f"enforce_{state_attr}"
    _enforce.__qualname__ = _enforce.__name__
    return _enforce

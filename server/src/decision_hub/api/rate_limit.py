"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import HTTPException, Request

# Default number of __call__ invocations between stale-IP sweeps.  Chosen large
# enough to keep amortised purge cost negligible, small enough that stale IPs
# don't pile up under steady traffic.
_DEFAULT_PURGE_INTERVAL = 256


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

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        *,
        purge_interval: int = _DEFAULT_PURGE_INTERVAL,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.purge_interval = purge_interval
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._calls_since_purge = 0

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
                        f"Rate limit exceeded ({self.max_requests} requests per {self.window_seconds}s). "
                        "Try again shortly."
                    ),
                )

            self._requests[key].append(now)

            # Amortised stale-IP sweep using a single counter (O(1) per call)
            # rather than recomputing the total queue size each time, which was
            # O(N_ips) and turned every rate-limited request into a hot path.
            self._calls_since_purge += 1
            if self._calls_since_purge >= self.purge_interval:
                self._calls_since_purge = 0
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def make_rate_limit_dep(name: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency that enforces ``{name}_rate_limit`` per IP.

    The returned callable lazily constructs a :class:`RateLimiter` on the
    application state and reuses it for the lifetime of the process.  The
    limiter draws its bounds from ``settings.{name}_rate_limit`` and
    ``settings.{name}_rate_window``, so adding a new endpoint requires only:

        1. ``{name}_rate_limit`` / ``{name}_rate_window`` in ``Settings``
        2. ``dependencies=[Depends(make_rate_limit_dep("foo"))]`` at the route

    Previously every endpoint hand-rolled the same lazy-init block (8 copies
    across 3 modules); this factory replaces all of them.
    """
    state_attr = f"_{name}_rate_limiter"
    limit_attr = f"{name}_rate_limit"
    window_attr = f"{name}_rate_window"

    def _enforce(request: Request) -> None:
        state = request.app.state
        limiter: RateLimiter | None = getattr(state, state_attr, None)
        if limiter is None:
            settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, limit_attr),
                window_seconds=getattr(settings, window_attr),
            )
            setattr(state, state_attr, limiter)
        limiter(request)

    _enforce.__name__ = f"_enforce_{name}_rate_limit"
    _enforce.__qualname__ = _enforce.__name__
    return _enforce

"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from collections.abc import Callable

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


_LIMITER_INIT_LOCK = threading.Lock()


def make_rate_limit_dep(name: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency that enforces a named per-IP rate limit.

    The limiter reads ``settings.{name}_rate_limit`` and ``settings.{name}_rate_window``
    and is lazily cached on ``app.state`` under ``_{name}_rate_limiter``. Cold-start
    initialisation is guarded by a module-level lock so concurrent requests don't
    race to create competing limiters.

    Usage::

        _enforce_search_rate_limit = make_rate_limit_dep("search")

        @router.get("/search", dependencies=[Depends(_enforce_search_rate_limit)])
        def search(...): ...
    """
    state_attr = f"_{name}_rate_limiter"
    limit_attr = f"{name}_rate_limit"
    window_attr = f"{name}_rate_window"

    def dep(request: Request) -> None:
        state = request.app.state
        limiter: RateLimiter | None = getattr(state, state_attr, None)
        if limiter is None:
            with _LIMITER_INIT_LOCK:
                # Re-check after acquiring the lock — another thread may have created it.
                limiter = getattr(state, state_attr, None)
                if limiter is None:
                    settings = state.settings
                    limiter = RateLimiter(
                        max_requests=getattr(settings, limit_attr),
                        window_seconds=getattr(settings, window_attr),
                    )
                    setattr(state, state_attr, limiter)
        limiter(request)

    dep.__name__ = f"_enforce_{name}_rate_limit"
    dep.__qualname__ = dep.__name__
    return dep

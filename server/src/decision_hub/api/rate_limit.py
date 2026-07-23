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

    # Purge stale IPs every N calls. Bounds memory without doing an O(N)
    # sweep on every request.
    _PURGE_EVERY = 100

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._call_count = 0

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

            # Periodic global purge to bound memory. A monotonic counter
            # avoids the O(N) sum previously used to decide when to sweep.
            self._call_count += 1
            if self._call_count % self._PURGE_EVERY == 0:
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def rate_limit_dependency(name: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency that enforces a named per-IP rate limit.

    Reads ``{name}_rate_limit`` and ``{name}_rate_window`` from
    ``request.app.state.settings`` on first invocation, lazily building a
    :class:`RateLimiter` and caching it as ``app.state._{name}_rate_limiter``.
    Subsequent requests reuse the cached limiter.

    Usage::

        _enforce_search_rate_limit = rate_limit_dependency("search")

        @router.get("/search", dependencies=[Depends(_enforce_search_rate_limit)])
        def search(...): ...
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
    _enforce.__doc__ = f"FastAPI dependency: enforce per-IP rate limit '{name}' from settings."
    return _enforce

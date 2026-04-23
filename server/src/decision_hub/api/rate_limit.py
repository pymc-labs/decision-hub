"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import HTTPException, Request

# Run stale-IP purge every N guarded accesses to keep memory bounded even when
# many short-lived clients each hit the limiter once. Using a dedicated counter
# (instead of ``sum(len(v) for v in ...) % N``) avoids a race where several
# concurrent callers can skip over a modulo boundary and leave the dictionary
# to grow without bound.
_PURGE_EVERY = 100


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
        self._calls = 0

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

            # Periodically purge stale IPs to bound memory growth. A dedicated
            # counter makes the trigger deterministic; ``sum(...) % N`` would
            # skip boundaries as prunes shrink other keys.
            self._calls += 1
            if self._calls >= _PURGE_EVERY:
                self._purge_stale(cutoff)
                self._calls = 0

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def rate_limit_dependency(name: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency enforcing a named rate limit.

    ``name`` must match a pair of settings fields: ``<name>_rate_limit``
    (max requests) and ``<name>_rate_window`` (window in seconds).  The
    underlying ``RateLimiter`` is created lazily on the first request
    and cached on ``request.app.state`` as ``_<name>_rate_limiter``, so
    the same instance is shared across requests within a container.

    Usage::

        _enforce_search_rate_limit = rate_limit_dependency("search")

        @router.get("/search", dependencies=[Depends(_enforce_search_rate_limit)])
        def search(...): ...
    """
    cache_attr = f"_{name}_rate_limiter"
    limit_field = f"{name}_rate_limit"
    window_field = f"{name}_rate_window"

    def dependency(request: Request) -> None:
        state = request.app.state
        limiter: RateLimiter | None = getattr(state, cache_attr, None)
        if limiter is None:
            settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, limit_field),
                window_seconds=getattr(settings, window_field),
            )
            setattr(state, cache_attr, limiter)
        limiter(request)

    dependency.__name__ = f"enforce_{name}_rate_limit"
    dependency.__qualname__ = dependency.__name__
    return dependency

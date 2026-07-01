"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import HTTPException, Request


def make_rate_limiter_dep(name: str) -> Callable[[Request], None]:
    """Return a FastAPI dependency that enforces a named rate limit.

    The limiter is lazily instantiated on ``app.state`` under
    ``rate_limiters[name]`` on first request and re-used thereafter.
    The corresponding settings must be present as ``settings.{name}_rate_limit``
    and ``settings.{name}_rate_window``.

    Replaces the copy-pasted ``_enforce_*_rate_limit`` factories that used
    to live in every route module.
    """

    def _dep(request: Request) -> None:
        state = request.app.state
        limiters: dict[str, RateLimiter] = getattr(state, "rate_limiters", None) or {}
        limiter = limiters.get(name)
        if limiter is None:
            settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, f"{name}_rate_limit"),
                window_seconds=getattr(settings, f"{name}_rate_window"),
            )
            limiters[name] = limiter
            state.rate_limiters = limiters
        limiter(request)

    _dep.__name__ = f"enforce_{name}_rate_limit"
    return _dep


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

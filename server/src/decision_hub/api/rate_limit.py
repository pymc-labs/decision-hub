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


def make_rate_limit_dep(name: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency that enforces a named rate limit.

    The factory reads ``settings.{name}_rate_limit`` and
    ``settings.{name}_rate_window`` from ``request.app.state.settings``
    on first use, builds a :class:`RateLimiter`, and caches it on
    ``app.state._{name}_rate_limiter``. Subsequent requests reuse the same
    limiter instance so the sliding window persists across calls.

    Replaces the family of ``_enforce_<name>_rate_limit(request)`` helpers
    that were copy-pasted across every route module — each one was the same
    9-line ``hasattr`` / ``setattr`` dance with only the setting names
    changing. Now adding a new rate-limited endpoint is one line at the
    module top::

        _enforce_publish_rate_limit = make_rate_limit_dep("publish")

        @router.post("/publish", dependencies=[Depends(_enforce_publish_rate_limit)])
        ...

    Args:
        name: Logical name of the rate limit. Must match the prefix of the
            ``Settings`` fields (e.g. ``"publish"`` for ``publish_rate_limit``
            / ``publish_rate_window``).

    Returns:
        A dependency callable suitable for ``fastapi.Depends(...)``.
    """
    state_attr = f"_{name}_rate_limiter"
    limit_attr = f"{name}_rate_limit"
    window_attr = f"{name}_rate_window"

    def dependency(request: Request) -> None:
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

    # Give the closure a stable name so FastAPI's dependency-cache key
    # and any debugging output (e.g. tracebacks) carry the intent.
    dependency.__name__ = f"_enforce_{name}_rate_limit"
    dependency.__qualname__ = dependency.__name__
    return dependency

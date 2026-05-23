"""In-memory sliding-window rate limiter for FastAPI dependencies."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from decision_hub.settings import Settings

# How often to sweep stale per-IP entries. Bounded by wall-clock so the
# memory ceiling is independent of request volume.
_PURGE_INTERVAL_SECONDS = 60.0


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
        self._last_purge: float = time.monotonic()

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
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

            # Bound memory by sweeping stale IPs on a wall-clock cadence
            # rather than a counter heuristic (which never fired under
            # uneven traffic). Cheap: scans the dict once per minute.
            if now - self._last_purge > _PURGE_INTERVAL_SECONDS:
                self._purge_stale(cutoff)
                self._last_purge = now

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def make_rate_limit_dep(name: str, limit_attr: str, window_attr: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency that lazily creates a per-endpoint rate limiter.

    Replaces the 7-line ``_enforce_*_rate_limit`` factory functions that
    were duplicated across every routes module.  The limiter is cached on
    ``app.state`` under ``_{name}_rate_limiter`` so it is created once per
    container and shared across requests.

    Args:
        name: Unique slug used for the cache key on ``app.state``.
        limit_attr: Name of the ``Settings`` field holding ``max_requests``.
        window_attr: Name of the ``Settings`` field holding ``window_seconds``.

    Returns:
        A callable suitable for use as a FastAPI ``Depends`` target.
    """
    cache_attr = f"_{name}_rate_limiter"

    def dependency(request: Request) -> None:
        state = request.app.state
        limiter: RateLimiter | None = getattr(state, cache_attr, None)
        if limiter is None:
            settings: Settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, limit_attr),
                window_seconds=getattr(settings, window_attr),
            )
            setattr(state, cache_attr, limiter)
        limiter(request)

    dependency.__name__ = f"enforce_{name}_rate_limit"
    dependency.__doc__ = f"Rate-limit the {name} endpoint."
    return dependency

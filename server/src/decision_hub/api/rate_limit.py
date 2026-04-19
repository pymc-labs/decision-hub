"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request


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

    # Purge stale IP entries every N enforced requests. Using a simple
    # local counter avoids the previous O(N_ips) sum() on every call.
    _PURGE_EVERY = 100

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._calls_since_purge = 0

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = [t for t in self._requests[key] if t > cutoff]

            if len(timestamps) >= self.max_requests:
                # Keep the pruned list even on reject so the next call sees
                # the current state without re-pruning.
                self._requests[key] = timestamps
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests "
                        f"per {self.window_seconds}s). Try again shortly."
                    ),
                )

            timestamps.append(now)
            self._requests[key] = timestamps

            self._calls_since_purge += 1
            if self._calls_since_purge >= self._PURGE_EVERY:
                self._calls_since_purge = 0
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def rate_limit_dep(name: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency that lazily initialises a named rate limiter.

    Each route was previously wired with a near-identical ``_enforce_*_rate_limit``
    function; this factory collapses them into one call site per route. The
    limiter instance is cached on ``app.state`` under a stable attribute so
    every request reuses it, and the ``{name}_rate_limit`` / ``{name}_rate_window``
    settings fields drive max requests and the sliding window.

    Args:
        name: Settings prefix — e.g. ``"search"`` reads ``settings.search_rate_limit``
            and ``settings.search_rate_window``.

    Returns:
        A FastAPI-compatible dependency callable.
    """
    state_attr = f"_rate_limiter_{name}"
    limit_attr = f"{name}_rate_limit"
    window_attr = f"{name}_rate_window"

    def _dep(request: Request) -> None:
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

    _dep.__name__ = f"rate_limit_{name}"
    return _dep


def rate_limit(name: str) -> "Depends":  # type: ignore[valid-type]
    """Shorthand: ``dependencies=[rate_limit("search")]`` at route definition."""
    return Depends(rate_limit_dep(name))

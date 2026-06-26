"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from starlette.datastructures import State


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


# Single lock that guards lazy creation of all per-name limiters on app.state.
# The `hasattr` / setattr dance below is otherwise racy under the FastAPI sync
# threadpool: two threads could both miss the attribute and create separate
# limiter instances, the second silently overwriting the first's tracking
# state. Creation only happens once per limiter name per process, so a single
# coarse lock is cheap and avoids the need for per-name locks.
_LIMITER_INIT_LOCK = threading.Lock()


def get_or_create_limiter(
    state: "State",
    name: str,
    max_requests: int,
    window_seconds: int,
) -> RateLimiter:
    """Return the limiter named ``name`` from ``state``, creating it on first use.

    The limiter is stored on ``state`` as the attribute ``_<name>_rate_limiter``.
    Used to back per-endpoint FastAPI dependencies — see ``enforce_rate_limit``.
    """
    attr = f"_{name}_rate_limiter"
    limiter = getattr(state, attr, None)
    if limiter is not None:
        return limiter
    with _LIMITER_INIT_LOCK:
        # Re-check under the lock to avoid clobbering an instance another
        # thread created while we were waiting.
        limiter = getattr(state, attr, None)
        if limiter is None:
            limiter = RateLimiter(max_requests=max_requests, window_seconds=window_seconds)
            setattr(state, attr, limiter)
    return limiter


def enforce_rate_limit(name: str, max_attr: str, window_attr: str):
    """Build a FastAPI dependency that rate-limits requests.

    Reads ``max_attr`` and ``window_attr`` from ``request.app.state.settings``
    on first use and caches the limiter on ``request.app.state``. Returns a
    callable suitable for ``Depends(...)``.
    """

    def _dep(request: Request) -> None:
        state = request.app.state
        settings = state.settings
        limiter = get_or_create_limiter(
            state,
            name,
            getattr(settings, max_attr),
            getattr(settings, window_attr),
        )
        limiter(request)

    _dep.__name__ = f"enforce_{name}_rate_limit"
    return _dep

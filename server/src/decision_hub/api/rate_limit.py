"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import HTTPException, Request

# Purge stale IPs every N calls. Cheap counter beats scanning the whole
# dict on every request just to compute a modulo trigger.
_PURGE_INTERVAL_CALLS = 100


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
        # Number of calls since the last stale-IP purge. Using a counter
        # avoids the previous O(N) `sum(len(v) for v in self._requests.values())`
        # scan on every request, which grew with the tracked-IP set.
        self._calls_since_purge = 0

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            # Prune expired timestamps for this key.
            fresh = [t for t in self._requests[key] if t > cutoff]

            if len(fresh) >= self.max_requests:
                # Persist the pruned list so we don't leak old entries even
                # when the request is rejected.
                self._requests[key] = fresh
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests "
                        f"per {self.window_seconds}s). Try again shortly."
                    ),
                )

            fresh.append(now)
            self._requests[key] = fresh

            # Periodically purge IPs with no recent activity to bound memory.
            self._calls_since_purge += 1
            if self._calls_since_purge >= _PURGE_INTERVAL_CALLS:
                self._purge_stale(cutoff)
                self._calls_since_purge = 0

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def rate_limit_dep(
    name: str,
    *,
    limit_attr: str,
    window_attr: str,
) -> Callable[[Request], None]:
    """Return a FastAPI dependency that enforces a per-IP rate limit.

    Lazily initializes a shared ``RateLimiter`` on ``request.app.state`` the
    first time the dependency runs, keyed by ``name``. Subsequent calls reuse
    the same limiter for the container's lifetime.

    Replaces ~9 near-identical ``_enforce_*_rate_limit`` helpers that all did
    the same lazy-init dance with only the settings-attribute names changing.

    Args:
        name: Unique identifier for the limiter (used as the app.state key).
        limit_attr: Name of the ``max_requests`` value on ``Settings``.
        window_attr: Name of the ``window_seconds`` value on ``Settings``.

    Returns:
        A callable suitable for ``fastapi.Depends(...)`` that raises
        HTTP 429 when the caller exceeds the configured budget.
    """
    state_attr = f"_rate_limiter_{name}"

    def enforce(request: Request) -> None:
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

    enforce.__name__ = f"_enforce_{name}_rate_limit"
    return enforce

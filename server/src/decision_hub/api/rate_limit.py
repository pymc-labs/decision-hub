"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import HTTPException, Request

from decision_hub.settings import Settings


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


# Lock guarding lazy-init of shared limiters on ``app.state``.  FastAPI runs
# sync dependencies in a threadpool, so two first-time hits from different
# threads could otherwise construct two separate limiter objects and lose
# request counts.
_STATE_INIT_LOCK = threading.Lock()


def rate_limit_dependency(
    attr_name: str,
    settings_getter: Callable[[Settings], tuple[int, int]],
) -> Callable[[Request], None]:
    """Return a FastAPI dependency that enforces a per-IP rate limit.

    Args:
        attr_name: Attribute name to memoize the limiter under on
            ``request.app.state`` — must be unique per limiter.
        settings_getter: Callable that pulls the ``(max_requests,
            window_seconds)`` pair out of the app's ``Settings`` instance.

    The dependency lazily instantiates the underlying :class:`RateLimiter`
    on first use. Instantiation is guarded by a module-level lock so the
    same limiter can't be created twice under concurrent first-time hits.

    This factory replaces ~60 lines of copy-pasted lazy-init blocks that
    previously lived in each route module (one per endpoint).
    """

    def _dep(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, attr_name, None)
        if limiter is None:
            with _STATE_INIT_LOCK:
                # Re-check inside the lock in case another thread just built it.
                limiter = getattr(state, attr_name, None)
                if limiter is None:
                    max_requests, window_seconds = settings_getter(state.settings)
                    limiter = RateLimiter(max_requests=max_requests, window_seconds=window_seconds)
                    setattr(state, attr_name, limiter)
        limiter(request)

    return _dep

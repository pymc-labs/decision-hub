"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
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
        # Plain dict (not defaultdict) so reads never create empty entries
        # and stale IPs can be reliably pruned.
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        # Counter for opportunistic stale-entry purging. Triggers on a
        # request count, not on the number of stored timestamps, so the
        # cleanup cadence stays predictable under any traffic shape.
        self._requests_since_purge = 0

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            existing = self._requests.get(key)
            # Prune expired timestamps for this IP; reuse the list to
            # avoid leaving stale entries behind.
            timestamps = [] if existing is None else [t for t in existing if t > cutoff]

            if len(timestamps) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests per {self.window_seconds}s). "
                        "Try again shortly."
                    ),
                )

            timestamps.append(now)
            self._requests[key] = timestamps

            # Purge stale IPs every N requests to bound memory growth.
            # Using a request counter (not list size) means the cleanup
            # runs at a predictable rate regardless of how many timestamps
            # any single IP has accumulated.
            self._requests_since_purge += 1
            if self._requests_since_purge >= 100:
                self._requests_since_purge = 0
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


# ---------------------------------------------------------------------------
# FastAPI dependency factory
# ---------------------------------------------------------------------------
#
# Every rate-limited endpoint used to define its own ``_enforce_*_rate_limit``
# function that lazily initialised a ``RateLimiter`` on ``app.state`` and
# read its limits from ``settings``.  That boilerplate was repeated 8 times
# across registry_routes, search_routes and auth_routes.  This factory
# collapses it to a single helper.
#
# Limiters are stored on ``app.state`` under ``_rate_limiter_<name>`` so
# they survive across requests within a Modal container but stay scoped
# per-app (multiple FastAPI apps in the same process would not share
# counters).


def rate_limit_dependency(name: str, limit_field: str, window_field: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency that enforces a per-IP rate limit.

    ``name`` identifies the limiter on ``app.state`` (one limiter per name).
    ``limit_field`` and ``window_field`` are the ``Settings`` attribute
    names that hold the configured request count and window seconds.

    The returned callable is suitable for ``Depends(...)``::

        enforce_publish_rate_limit = rate_limit_dependency(
            "publish", "publish_rate_limit", "publish_rate_window",
        )

        @router.post("/publish", dependencies=[Depends(enforce_publish_rate_limit)])
        def publish(...): ...
    """
    state_attr = f"_rate_limiter_{name}"

    def dependency(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, state_attr, None)
        if limiter is None:
            settings: Settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, limit_field),
                window_seconds=getattr(settings, window_field),
            )
            setattr(state, state_attr, limiter)
        limiter(request)

    dependency.__name__ = f"enforce_{name}_rate_limit"
    dependency.__qualname__ = dependency.__name__
    return dependency

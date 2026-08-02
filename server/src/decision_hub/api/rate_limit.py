"""In-memory sliding-window rate limiter for FastAPI dependencies.

The public helper is :func:`rate_limit_dep`, which returns a FastAPI
dependency that lazily instantiates one :class:`RateLimiter` per named
bucket on the app state. Endpoints wire it up like::

    dependencies=[Depends(rate_limit_dep("search"))]

The bucket name (``"search"``) drives two conventions:

* the settings fields ``<bucket>_rate_limit`` / ``<bucket>_rate_window``
* the app-state attribute ``_rate_limiter_<bucket>`` for reuse

This replaces the previous pattern of writing a dedicated
``_enforce_<bucket>_rate_limit`` helper per endpoint — 9 near-identical
copies had grown across ``registry_routes``, ``search_routes``, and
``auth_routes``.
"""

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

    # Prune stale IP buckets every N accepted requests. Kept as a class
    # attribute so tests can lower it without patching the module.
    _PURGE_INTERVAL: int = 256

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        # Cheap O(1) counter — avoids sum() over every bucket per request.
        self._accepted_since_purge = 0

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            # Prune expired timestamps for this key
            timestamps = self._requests[key]
            fresh = [t for t in timestamps if t > cutoff]

            if len(fresh) >= self.max_requests:
                # Overwrite so the freshly pruned list is retained even
                # when we reject — avoids unbounded growth for a hot
                # attacker IP.
                self._requests[key] = fresh
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests per {self.window_seconds}s). Try again shortly."
                    ),
                )

            fresh.append(now)
            self._requests[key] = fresh

            # Periodically drop IPs with no recent activity. Runs off a
            # simple accepted-request counter so it's O(1) per request
            # instead of the old O(N-buckets) sum.
            self._accepted_since_purge += 1
            if self._accepted_since_purge >= self._PURGE_INTERVAL:
                self._purge_stale(cutoff)
                self._accepted_since_purge = 0

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def _get_or_create_limiter(request: Request, bucket: str) -> RateLimiter:
    """Return the RateLimiter for *bucket*, creating it on first use.

    Reads ``<bucket>_rate_limit`` and ``<bucket>_rate_window`` from
    ``app.state.settings`` and caches the limiter under
    ``app.state._rate_limiter_<bucket>``.
    """
    state = request.app.state
    attr = f"_rate_limiter_{bucket}"
    limiter = getattr(state, attr, None)
    if limiter is None:
        settings: Settings = state.settings
        limiter = RateLimiter(
            max_requests=getattr(settings, f"{bucket}_rate_limit"),
            window_seconds=getattr(settings, f"{bucket}_rate_window"),
        )
        setattr(state, attr, limiter)
    return limiter


def rate_limit_dep(bucket: str) -> Callable[[Request], None]:
    """Return a FastAPI dependency that rate-limits requests for *bucket*.

    ``bucket`` names the settings pair (``<bucket>_rate_limit`` /
    ``<bucket>_rate_window``) and the cached app-state attribute
    (``_rate_limiter_<bucket>``). One helper per bucket replaces the
    previous per-endpoint ``_enforce_*_rate_limit`` copies.
    """

    def _enforce(request: Request) -> None:
        _get_or_create_limiter(request, bucket)(request)

    _enforce.__name__ = f"enforce_{bucket}_rate_limit"
    _enforce.__doc__ = f"Rate-limit dependency for the {bucket!r} bucket."
    return _enforce

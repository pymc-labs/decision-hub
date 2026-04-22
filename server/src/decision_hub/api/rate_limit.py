"""In-memory sliding-window rate limiter for FastAPI dependencies.

This module exposes two things:

* ``RateLimiter`` — the per-IP sliding-window limiter itself.
* ``rate_limit_dep`` — a small factory that lazily constructs a limiter
  from ``Settings`` fields and returns it as a FastAPI dependency.  Routes
  wire it via ``Depends(rate_limit_dep("search"))`` instead of defining a
  one-off ``_enforce_*_rate_limit`` closure per endpoint.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from fastapi import HTTPException, Request

from decision_hub.settings import Settings


class RateLimiter:
    """Per-IP sliding-window rate limiter.

    Tracks request timestamps per client IP in memory.  Works well for
    Modal serverless containers where each container handles its own
    traffic — counters are not shared across containers, and that's
    acceptable for preventing a single client from hammering a single
    container.

    Thread-safe: FastAPI runs sync dependencies in a threadpool, so
    concurrent access to shared state is guarded by a lock.

    Usage as a FastAPI dependency::

        limiter = RateLimiter(max_requests=10, window_seconds=60)

        @router.get("/search", dependencies=[Depends(limiter)])
        def search(...): ...
    """

    # How often to run the "purge stale IPs" sweep.  A bounded counter
    # is cheaper and more deterministic than the previous
    # ``sum(len(v) for v in ...) % 100 == 0`` check which was O(n) per
    # request and fired every time when the map was empty.
    _PURGE_INTERVAL = 100

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # Plain dict, not defaultdict: we want to explicitly decide when
        # to allocate a new bucket, so reads never leave empty lists
        # behind.
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._since_purge = 0

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            existing = self._requests.get(key)
            # Prune expired timestamps for this key.  Unknown keys stay
            # unrepresented in ``self._requests`` until we actually append
            # a timestamp below, so reads never leave empty buckets behind.
            timestamps = [t for t in existing if t > cutoff] if existing else []

            if len(timestamps) >= self.max_requests:
                # Keep the pruned state so we don't grow the bucket
                # back on every subsequent 429.
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

            self._since_purge += 1
            if self._since_purge >= self._PURGE_INTERVAL:
                self._since_purge = 0
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Drop IPs with no recent activity. Caller must hold ``self._lock``."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def rate_limit_dep(name: str) -> Callable[[Request], None]:
    """Return a FastAPI dependency enforcing a settings-driven rate limit.

    Replaces the old pattern of defining a bespoke ``_enforce_X_rate_limit``
    function per endpoint.  The limiter is constructed lazily on first use
    and stashed on ``app.state._rate_limiters`` so every route sharing a
    name sees the same bucket.

    Args:
        name: Settings prefix — e.g. ``"search"`` resolves to
            ``settings.search_rate_limit`` and ``settings.search_rate_window``.

    Returns:
        A callable suitable for ``Depends(...)``.
    """
    limit_attr = f"{name}_rate_limit"
    window_attr = f"{name}_rate_window"

    def _dep(request: Request) -> None:
        state = request.app.state
        registry: dict[str, RateLimiter] | None = getattr(state, "_rate_limiters", None)
        if registry is None:
            registry = {}
            state._rate_limiters = registry

        limiter = registry.get(name)
        if limiter is None:
            settings: Settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, limit_attr),
                window_seconds=getattr(settings, window_attr),
            )
            registry[name] = limiter

        limiter(request)

    _dep.__name__ = f"rate_limit_{name}"
    return _dep

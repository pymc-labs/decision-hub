"""In-memory sliding-window rate limiter for FastAPI dependencies."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request

# Periodic GC: scan the full per-IP map after this many requests to drop
# IPs that have gone idle. Chosen so a single 100-burst client never
# triggers a scan, but a steady stream of distinct IPs is bounded.
_GC_INTERVAL = 1024


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
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # Plain dict (not defaultdict): reading an unknown IP must not
        # implicitly create an entry, otherwise idle GET-misses could
        # bloat the map.
        self._requests: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        # Monotonically increases on every request so periodic GC fires
        # on a request *count*, not on the (often-zero) total queue
        # length. The previous heuristic ``sum(...) % 100 == 0`` fired
        # on every call whenever the map was empty.
        self._request_count = 0

    def __call__(self, request: Request) -> None:
        key = _client_key(request)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._requests.get(key)
            if timestamps is None:
                timestamps = deque()
                self._requests[key] = timestamps
            else:
                # Drop expired timestamps from the front. deque.popleft
                # is O(1); rebuilding the list each call was O(n).
                while timestamps and timestamps[0] <= cutoff:
                    timestamps.popleft()

            if len(timestamps) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests "
                        f"per {self.window_seconds}s). Try again shortly."
                    ),
                )

            timestamps.append(now)

            self._request_count += 1
            if self._request_count % _GC_INTERVAL == 0:
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold ``self._lock``."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] <= cutoff]
        for k in stale:
            del self._requests[k]


def _client_key(request: Request) -> str:
    """Return the client identifier used for rate-limiting buckets.

    Falls back to ``"unknown"`` when the ASGI server cannot determine
    a peer address (rare; happens with some test clients).
    """
    client = request.client
    return client.host if client is not None else "unknown"


def make_rate_limit_dep(
    name: str,
    limit_attr: str,
    window_attr: str,
) -> Callable[[Request], None]:
    """Build a FastAPI dependency that lazily provisions a ``RateLimiter``.

    The limiter is cached on ``request.app.state`` under the attribute
    ``f"_{name}_rate_limiter"`` so the first request through any worker
    initialises it once, then reuses it. Settings are read from
    ``state.settings.<limit_attr>`` / ``<window_attr>``, which keeps
    runtime configuration (env-driven) close to the dependency.

    This replaces ~10 lines of boilerplate per endpoint with a single
    declarative call site.
    """
    state_attr = f"_{name}_rate_limiter"

    def _enforce(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, state_attr, None)
        if limiter is None:
            settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, limit_attr),
                window_seconds=getattr(settings, window_attr),
            )
            # Last writer wins under the unlikely concurrent-init race;
            # either limiter is fresh and equivalent, so traffic isn't
            # double-counted in any meaningful sense.
            setattr(state, state_attr, limiter)
        limiter(request)

    _enforce.__name__ = f"_enforce_{name}_rate_limit"
    _enforce.__qualname__ = _enforce.__name__
    _enforce.__doc__ = f"Rate-limit dependency backed by settings.{limit_attr} / {window_attr}."
    return _enforce

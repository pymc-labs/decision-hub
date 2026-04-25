"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

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

    Args:
        max_requests: Maximum number of requests allowed per window.
        window_seconds: Sliding window length in seconds.
        trust_forwarded_for: When True, derive the client identifier from
            the leftmost ``X-Forwarded-For`` entry instead of the direct
            socket address. Required when the app sits behind a proxy or
            ingress (e.g. Modal). Disabled by default because the header
            is trivial to spoof when the deployment is *not* behind such
            a proxy.
    """

    # Run periodic stale-IP purge every N admitted requests. A counter
    # is cheaper than O(N) summing over all tracked IPs on every request.
    _PURGE_EVERY = 100

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        *,
        trust_forwarded_for: bool = False,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.trust_forwarded_for = trust_forwarded_for
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._admitted_since_purge = 0

    def _client_key(self, request: Request) -> str:
        """Pick a stable identifier for the calling client.

        Prefers the leftmost X-Forwarded-For entry when ``trust_forwarded_for``
        is enabled. Falls back to the socket peer address. Returns ``"unknown"``
        when neither is available.
        """
        if self.trust_forwarded_for:
            xff = request.headers.get("x-forwarded-for")
            if xff:
                first = xff.split(",", 1)[0].strip()
                if first:
                    return first
        return request.client.host if request.client else "unknown"

    def __call__(self, request: Request) -> None:
        key = self._client_key(request)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._requests[key]
            # Prune expired timestamps for this key in place — avoids
            # rebinding the dict slot and the allocation that came with it.
            timestamps[:] = [t for t in timestamps if t > cutoff]

            if len(timestamps) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests "
                        f"per {self.window_seconds}s). Try again shortly."
                    ),
                )

            timestamps.append(now)

            # Periodically purge stale IPs to bound memory growth. Driving
            # this off a counter (O(1)) instead of summing all buckets
            # (O(N)) keeps per-request cost constant as the IP set grows.
            self._admitted_since_purge += 1
            if self._admitted_since_purge >= self._PURGE_EVERY:
                self._purge_stale(cutoff)
                self._admitted_since_purge = 0

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def make_rate_limiter_dep(
    state_attr: str,
    *,
    get_max_requests: Callable[[Any], int],
    get_window_seconds: Callable[[Any], int],
    trust_forwarded_for: bool = False,
) -> Callable[[Request], None]:
    """Build a FastAPI dependency that enforces a per-route rate limit.

    The limiter is created on first use and cached on ``app.state`` under
    ``state_attr`` so that all requests for the same route share the same
    sliding window. Construction is guarded by a process-wide lock to
    prevent two concurrent first-callers from creating duplicate limiters.

    Settings are read lazily so they can be overridden in tests *after*
    the dependency is registered.

    Args:
        state_attr: Attribute name to use on ``app.state`` for the cached
            limiter. Use a unique string per route group.
        get_max_requests: Callable that accepts the ``Settings`` object
            and returns the per-route max-requests value.
        get_window_seconds: Same, for the per-route window length.
        trust_forwarded_for: Forwarded to ``RateLimiter``. See its docstring.

    Returns:
        A FastAPI dependency callable. Use as
        ``dependencies=[Depends(my_limiter)]`` on a route.
    """
    init_lock = threading.Lock()

    def _dep(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, state_attr, None)
        if limiter is None:
            with init_lock:
                # Re-check inside the lock so concurrent first-callers
                # don't each instantiate their own limiter.
                limiter = getattr(state, state_attr, None)
                if limiter is None:
                    limiter = RateLimiter(
                        max_requests=get_max_requests(state.settings),
                        window_seconds=get_window_seconds(state.settings),
                        trust_forwarded_for=trust_forwarded_for,
                    )
                    setattr(state, state_attr, limiter)
        limiter(request)

    return _dep

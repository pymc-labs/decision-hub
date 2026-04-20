"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections.abc import Callable

from fastapi import HTTPException, Request

from decision_hub.settings import Settings


def _client_key(request: Request) -> str:
    """Return the originating client IP for rate-limit bucketing.

    Behind Modal / CloudFlare, ``request.client.host`` is the proxy IP,
    so every user appears in the same bucket and the limiter silently
    collapses into a single global bucket. Modal and standard reverse
    proxies populate ``X-Forwarded-For`` with the original client IP as
    the first (left-most) entry; prefer that when present and fall back
    to the direct peer otherwise.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        first = fwd.split(",", 1)[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


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
        # Explicit dict (not defaultdict) so a blocked client doesn't
        # leave an empty list entry behind after pruning.
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._since_purge = 0

    def __call__(self, request: Request) -> None:
        key = _client_key(request)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._requests.get(key)
            if timestamps is not None:
                timestamps = [t for t in timestamps if t > cutoff]
                if timestamps:
                    self._requests[key] = timestamps
                else:
                    self._requests.pop(key, None)

            current = self._requests.get(key, [])
            if len(current) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests per {self.window_seconds}s). Try again shortly."
                    ),
                )

            current.append(now)
            self._requests[key] = current

            # Periodically purge stale IPs to bound memory growth. A
            # dedicated counter runs the purge on a predictable cadence
            # regardless of request shape (``total % 100`` only fires
            # when total happens to land on 100).
            self._since_purge += 1
            if self._since_purge >= 100:
                self._purge_stale(cutoff)
                self._since_purge = 0

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def rate_limit_dep(
    attr: str,
    limit_setting: str,
    window_setting: str,
) -> Callable[[Request], None]:
    """Build a FastAPI dependency that lazily caches a per-endpoint limiter.

    Replaces the ``_enforce_*_rate_limit`` helpers that used to live in
    every routes module.  Each call site gets its own limiter stored on
    ``app.state.<attr>``; the limiter's sliding-window state is shared
    across requests but scoped to the endpoint.

    Args:
        attr: Attribute name used to cache the limiter on ``app.state``.
            Must be unique per endpoint.
        limit_setting: Name of a ``Settings`` int attribute giving the
            max request count per window.
        window_setting: Name of a ``Settings`` int attribute giving the
            window size in seconds.

    Returns:
        A FastAPI-compatible dependency callable.
    """

    def _dep(request: Request) -> None:
        state = request.app.state
        limiter: RateLimiter | None = getattr(state, attr, None)
        if limiter is None:
            settings: Settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, limit_setting),
                window_seconds=getattr(settings, window_setting),
            )
            setattr(state, attr, limiter)
        limiter(request)

    return _dep

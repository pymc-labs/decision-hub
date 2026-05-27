"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import HTTPException, Request

from decision_hub.settings import Settings


def client_ip(request: Request) -> str:
    """Return the originating client IP for rate-limiting purposes.

    Modal (and most reverse proxies) put the real client IP in the
    ``X-Forwarded-For`` header; ``request.client.host`` is the proxy's
    own address.  Without this lookup every user looks like one IP and
    the per-IP limiter becomes a global limiter — letting one abuser
    burn the budget for every legitimate client behind the same edge.

    The leftmost entry in ``X-Forwarded-For`` is the original client.
    Honour it whenever present; fall back to ``X-Real-IP`` and finally
    to the direct peer address.
    """
    headers = request.headers
    fwd = headers.get("x-forwarded-for")
    if fwd:
        # "client, proxy1, proxy2" — leftmost is the original client.
        first = fwd.split(",", 1)[0].strip()
        if first:
            return first
    real_ip = headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
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

    # Run the stale-IP sweep every Nth admission to bound memory.
    _PURGE_EVERY = 100

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._admitted_since_purge = 0

    def __call__(self, request: Request) -> None:
        key = client_ip(request)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            # Prune expired timestamps for this key.
            timestamps = [t for t in self._requests[key] if t > cutoff]
            if len(timestamps) >= self.max_requests:
                # Persist the pruned list so memory cannot grow on
                # rejected attempts; otherwise old entries would never
                # be cleared for this key until it admits one.
                self._requests[key] = timestamps
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests per {self.window_seconds}s). Try again shortly."
                    ),
                )

            timestamps.append(now)
            self._requests[key] = timestamps

            self._admitted_since_purge += 1
            if self._admitted_since_purge >= self._PURGE_EVERY:
                self._admitted_since_purge = 0
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def make_rate_limit_dep(name: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency that enforces a named rate limit.

    Looks up ``settings.{name}_rate_limit`` and ``settings.{name}_rate_window``
    on first use, then caches a :class:`RateLimiter` on ``app.state`` keyed by
    ``_rate_limiter_{name}`` so subsequent requests reuse the same instance.

    Centralising this eliminates the per-endpoint ``_enforce_*_rate_limit``
    boilerplate that previously lived in every routes module.

    Args:
        name: Settings prefix.  ``"publish"`` maps to ``publish_rate_limit``
              and ``publish_rate_window``.

    Returns:
        A callable suitable for ``dependencies=[Depends(...)]``.
    """
    state_attr = f"_rate_limiter_{name}"
    limit_attr = f"{name}_rate_limit"
    window_attr = f"{name}_rate_window"

    def dependency(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, state_attr, None)
        if limiter is None:
            settings: Settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, limit_attr),
                window_seconds=getattr(settings, window_attr),
            )
            setattr(state, state_attr, limiter)
        limiter(request)

    dependency.__name__ = f"rate_limit_{name}"
    return dependency

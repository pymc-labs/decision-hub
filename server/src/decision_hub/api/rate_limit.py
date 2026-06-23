"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from decision_hub.settings import Settings


def client_ip(request: Request) -> str:
    """Return the originating client IP, honouring proxy headers.

    Modal's edge (and most CDNs / load balancers) terminates TCP at the
    proxy, so ``request.client.host`` is the proxy IP — identical for
    every caller behind it.  We trust ``X-Forwarded-For`` (left-most
    entry is the original client) and ``X-Real-IP`` as a fallback, then
    finally the direct peer address.

    Returning the real client IP keeps the per-IP rate limiter from
    collapsing all traffic into a single bucket, which would let one
    noisy client lock out everyone else sharing the edge.
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    if request.client:
        return request.client.host
    return "unknown"


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
        key = client_ip(request)
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


def rate_limiter_dep(name: str):
    """Return a FastAPI dependency that lazily builds a named rate limiter.

    ``name`` is the prefix of two settings fields on ``Settings``:
    ``{name}_rate_limit`` (max requests) and ``{name}_rate_window``
    (window in seconds).  The limiter instance lives on ``app.state``
    under ``_rate_limiter_{name}`` and is shared across requests served
    by the same container.

    Replaces nine near-identical ``_enforce_*_rate_limit`` helpers that
    were copy-pasted across the route modules.  Adding a new limited
    endpoint is now one line of dependency wiring plus the two
    ``Settings`` fields.
    """
    attr = f"_rate_limiter_{name}"

    def _enforce(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, attr, None)
        if limiter is None:
            settings: Settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, f"{name}_rate_limit"),
                window_seconds=getattr(settings, f"{name}_rate_window"),
            )
            setattr(state, attr, limiter)
        limiter(request)

    _enforce.__name__ = f"enforce_{name}_rate_limit"
    _enforce.__doc__ = f"Per-IP rate limit for endpoints in the '{name}' group."
    return _enforce

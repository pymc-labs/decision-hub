"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import HTTPException, Request


def _client_key(request: Request, trust_proxy_hops: int) -> str:
    """Return the per-client identifier used for rate-limit bucketing.

    When the app sits behind one or more reverse proxies (Modal's edge,
    a CDN, an internal LB), ``request.client.host`` is the proxy address
    and every caller collapses into one bucket — defeating per-client
    limiting. With ``trust_proxy_hops > 0`` we read ``X-Forwarded-For``
    and pick the rightmost-but-N entry, which is the IP added by the
    last trusted proxy. Untrusted proxies appear earlier in the list and
    cannot spoof the client we attribute to.

    Falls back to ``request.client.host`` (or the literal ``"unknown"``)
    when no forwarded header is available or it can't be parsed.
    """
    if trust_proxy_hops > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # XFF is "client, proxy1, proxy2"; the IP added by the Nth
            # trusted hop from the right is the most trustworthy client.
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if parts:
                idx = max(0, len(parts) - trust_proxy_hops)
                candidate = parts[idx]
                if candidate:
                    return candidate
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Per-IP sliding-window rate limiter.

    Tracks request timestamps per client IP in memory. Works well for
    Modal serverless containers where each container handles its own
    traffic. Not shared across containers -- that's fine for preventing
    a single client from hammering a single container.

    Thread-safe: FastAPI runs sync dependencies in a threadpool, so
    concurrent access to shared state is guarded by a lock.

    Memory bound: stale IP buckets are purged once per ``window_seconds``,
    so the dict size is bounded by the number of distinct clients seen
    in the active window — not by total traffic. This prevents
    unique-IP fan-out (a many-source DoS) from growing memory unbounded
    before the next purge naturally fires.

    Usage as a FastAPI dependency::

        limiter = RateLimiter(max_requests=10, window_seconds=60)

        @router.get("/search", dependencies=[Depends(limiter)])
        def search(...): ...
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        *,
        trust_proxy_hops: int = 0,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.trust_proxy_hops = trust_proxy_hops
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        # Initialise so the first request schedules a purge one window
        # from now, not immediately.
        self._last_purge_at: float = time.monotonic()

    def __call__(self, request: Request) -> None:
        key = _client_key(request, self.trust_proxy_hops)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            # Time-driven purge: runs at most once per window regardless
            # of request shape, so a single client cannot delay cleanup
            # and many unique clients cannot defeat it.
            if now - self._last_purge_at >= self.window_seconds:
                self._purge_stale(cutoff)
                self._last_purge_at = now

            timestamps = self._requests[key]
            # Mutate in place so the defaultdict entry is the same list
            # object across calls. ``[:] = ...`` keeps memory churn low
            # and avoids reassigning the dict entry.
            timestamps[:] = [t for t in timestamps if t > cutoff]

            if len(timestamps) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests per {self.window_seconds}s). Try again shortly."
                    ),
                )

            timestamps.append(now)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        # Snapshot keys first so we don't mutate during iteration.
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def rate_limit_dep(
    state_attr: str,
    max_attr: str,
    window_attr: str,
) -> Callable[[Request], None]:
    """Build a FastAPI dependency that lazily creates a per-app RateLimiter.

    Centralises the previously-duplicated ``_enforce_*_rate_limit`` pattern
    that lived in every routes module. The limiter is stored on
    ``request.app.state`` under ``state_attr`` so each settings-backed
    endpoint gets its own counter without leaking limits between routes.

    Args:
        state_attr: Attribute name to cache the limiter on ``app.state``
            (e.g. ``"_search_rate_limiter"``).
        max_attr: ``Settings`` field providing the max requests per window.
        window_attr: ``Settings`` field providing the window in seconds.

    Returns:
        A callable suitable for use with ``Depends(...)``.
    """

    def _enforce(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, state_attr, None)
        if limiter is None:
            settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, max_attr),
                window_seconds=getattr(settings, window_attr),
                trust_proxy_hops=getattr(settings, "trust_proxy_hops", 0),
            )
            setattr(state, state_attr, limiter)
        limiter(request)

    return _enforce

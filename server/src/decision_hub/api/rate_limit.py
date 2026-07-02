"""In-memory sliding-window rate limiter for FastAPI dependencies.

Behind a proxy (Modal's LB), the direct peer IP is the LB itself so every
request would share one bucket. Set ``trusted_proxy_count`` on
``RateLimiter`` (wired from ``Settings.trusted_proxy_count``) to instead
read the caller IP from the right-most Nth entry in
``X-Forwarded-For`` -- N being the number of hops we trust.

The ``rate_limit_dependency`` factory below collapses the ~10 near-identical
``_enforce_*_rate_limit`` helpers each route module used to define into a
single lazy, thread-safe attach onto ``app.state``.
"""

import threading
import time
from collections import defaultdict, deque
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

    # Minimum seconds between stale-IP purges. The previous implementation
    # triggered when ``sum(len(v) for v in requests.values()) % 100 == 0``,
    # an O(N) computation on every request that could also miss the modulo
    # entirely as the fleet of unique IPs grew, leaking memory.
    _PURGE_INTERVAL_SECONDS = 60

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        trusted_proxy_count: int = 0,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.trusted_proxy_count = trusted_proxy_count
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_purge = 0.0

    def _client_ip(self, request: Request) -> str:
        """Resolve the client IP, honouring X-Forwarded-For when trusted.

        ``X-Forwarded-For`` is a comma-separated left-to-right chain of
        proxies. Each hop appends the peer it received the request from,
        so the *rightmost* entries are the ones we can trust (they were
        set by proxies we control). If we trust N hops, the client IP is
        N positions from the right; entries further left were set by
        untrusted middleboxes or the client itself and must be ignored.
        """
        if self.trusted_proxy_count > 0:
            xff = request.headers.get("x-forwarded-for", "")
            if xff:
                parts = [p.strip() for p in xff.split(",") if p.strip()]
                if parts:
                    # Clamp so a shorter-than-expected chain still resolves
                    # to the left-most (i.e. original) entry.
                    idx = max(0, len(parts) - self.trusted_proxy_count)
                    return parts[idx]
        return request.client.host if request.client else "unknown"

    def __call__(self, request: Request) -> None:
        key = self._client_ip(request)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._requests[key]
            # deque left-pop is O(1) per expired entry vs. rebuilding the list.
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests per {self.window_seconds}s). Try again shortly."
                    ),
                )

            timestamps.append(now)

            if now - self._last_purge >= self._PURGE_INTERVAL_SECONDS:
                self._purge_stale(cutoff)
                self._last_purge = now

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


# Guards the double-checked lazy-init pattern in ``rate_limit_dependency``.
# The ``hasattr(state, ...)`` + attribute-set pattern the routes used before
# was not atomic: two threads first-hitting simultaneously could each build
# their own ``RateLimiter`` and the loser's history was silently discarded.
_init_lock = threading.Lock()


def rate_limit_dependency(name: str) -> Callable[[Request], None]:
    """Return a FastAPI dependency that lazily attaches a RateLimiter to app.state.

    Given ``name="publish"``, the returned dependency reads
    ``Settings.publish_rate_limit`` / ``Settings.publish_rate_window``
    on first use and stores the built limiter as
    ``app.state._publish_rate_limiter`` for subsequent requests.

    Collapses the ~10 near-identical ``_enforce_*_rate_limit`` functions
    the route modules used to define into a single, tested helper.
    """
    attr = f"_{name}_rate_limiter"
    limit_field = f"{name}_rate_limit"
    window_field = f"{name}_rate_window"

    def _dep(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, attr, None)
        if limiter is None:
            with _init_lock:
                limiter = getattr(state, attr, None)
                if limiter is None:
                    settings: Settings = state.settings
                    limiter = RateLimiter(
                        max_requests=getattr(settings, limit_field),
                        window_seconds=getattr(settings, window_field),
                        trusted_proxy_count=settings.trusted_proxy_count,
                    )
                    setattr(state, attr, limiter)
        limiter(request)

    _dep.__name__ = f"_enforce_{name}_rate_limit"
    _dep.__qualname__ = _dep.__name__
    return _dep

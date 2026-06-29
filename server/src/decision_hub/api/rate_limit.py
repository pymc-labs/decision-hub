"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import HTTPException, Request

# Run a stale-IP sweep every PURGE_EVERY_REQUESTS calls (cheap, amortised).
_PURGE_EVERY_REQUESTS = 256

# Hard cap on the number of tracked IPs per limiter.  When exceeded, the
# limiter evicts arbitrary entries down to MAX_TRACKED_IPS to keep memory
# bounded under adversarial traffic from many unique IPs.
_MAX_TRACKED_IPS = 10_000


class RateLimiter:
    """Per-IP sliding-window rate limiter.

    Tracks request timestamps per client IP in memory. Works well for
    Modal serverless containers where each container handles its own
    traffic. Not shared across containers -- that's fine for preventing
    a single client from hammering a single container.

    Thread-safe: FastAPI runs sync dependencies in a threadpool, so
    concurrent access to shared state is guarded by a lock.

    Memory is bounded by:
    - Periodic stale-IP purging every ``_PURGE_EVERY_REQUESTS`` calls.
    - A hard cap (``_MAX_TRACKED_IPS``) that triggers eviction when many
      unique IPs hit the same container (e.g. a botnet sweep).

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
        # Cheap monotonic counter so we don't have to sum() the full dict
        # on every request to decide when to purge.
        self._call_count = 0

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
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

            self._call_count += 1
            if self._call_count % _PURGE_EVERY_REQUESTS == 0:
                self._purge_stale(cutoff)
            # Hard cap on tracked-IP count to bound memory even between
            # purges (e.g. under an unique-IP flood).
            if len(self._requests) > _MAX_TRACKED_IPS:
                self._evict_to_cap()

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]

    def _evict_to_cap(self) -> None:
        """Drop oldest-touched IPs until size <= _MAX_TRACKED_IPS.

        Caller must hold ``self._lock``.  Uses last-timestamp as the
        recency signal; ties broken arbitrarily by dict iteration order.
        """
        # Sort by most-recent timestamp ascending so oldest are first.
        ranked = sorted(
            self._requests.items(),
            key=lambda kv: kv[1][-1] if kv[1] else 0.0,
        )
        excess = len(self._requests) - _MAX_TRACKED_IPS
        for key, _ in ranked[:excess]:
            del self._requests[key]


def make_rate_limit_dep(name: str, max_attr: str, window_attr: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency that enforces a per-endpoint rate limit.

    The ``RateLimiter`` is created lazily on first request and cached on
    ``app.state`` under ``f"_{name}_rate_limiter"`` so each endpoint gets
    its own isolated counter without paying init cost at app startup.

    Args:
        name: Unique short identifier for this endpoint (e.g. ``"search"``).
            Used as the ``app.state`` attribute suffix.
        max_attr: Name of the ``Settings`` field holding the max requests
            (e.g. ``"search_rate_limit"``).
        window_attr: Name of the ``Settings`` field holding the window in
            seconds (e.g. ``"search_rate_window"``).
    """
    state_attr = f"_{name}_rate_limiter"

    def dependency(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, state_attr, None)
        if limiter is None:
            settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, max_attr),
                window_seconds=getattr(settings, window_attr),
            )
            setattr(state, state_attr, limiter)
        limiter(request)

    dependency.__name__ = f"_enforce_{name}_rate_limit"
    return dependency

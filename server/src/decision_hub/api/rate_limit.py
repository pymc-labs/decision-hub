"""In-memory sliding-window rate limiter for FastAPI dependencies.

The module exposes two layers:

* ``RateLimiter`` — the per-IP sliding-window primitive.
* ``make_rate_limit_dep(name)`` — a factory that returns a FastAPI
  dependency callable. The factory lazily reads
  ``settings.{name}_rate_limit`` / ``settings.{name}_rate_window`` from
  ``app.state`` on first invocation and caches one ``RateLimiter`` per
  name on ``app.state._rate_limiters``. This replaces what used to be
  nine near-identical ``_enforce_*_rate_limit`` functions duplicated
  across the route files.
"""

import threading
import time
from collections import defaultdict
from collections.abc import Callable

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
    """

    # How often to scan the full dict for stale IPs. The previous
    # implementation called ``sum(len(v) for v in self._requests.values())``
    # on every request, which is O(N) in the number of tracked IPs and
    # ran on the hottest pre-handler path. We now maintain an explicit
    # request counter and trigger a purge every _PURGE_INTERVAL requests
    # — same intent, O(1) per call.
    _PURGE_INTERVAL = 100

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
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

            # Periodically purge stale IPs to bound memory growth.
            self._call_count += 1
            if self._call_count >= self._PURGE_INTERVAL:
                self._call_count = 0
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def make_rate_limit_dep(name: str) -> Callable[[Request], None]:
    """Return a FastAPI dependency that enforces a named rate limit.

    The limiter is built lazily on first request from
    ``settings.{name}_rate_limit`` and ``settings.{name}_rate_window``
    and cached on ``app.state._rate_limiters[name]``. All endpoints
    sharing the same ``name`` share the same per-IP counters.

    Args:
        name: Settings prefix. The factory looks up
            ``{name}_rate_limit`` and ``{name}_rate_window`` on the
            ``Settings`` object stored in ``app.state.settings``.

    Returns:
        A callable suitable for ``Depends(...)`` in a FastAPI route.
    """

    def dep(request: Request) -> None:
        state = request.app.state
        limiters: dict[str, RateLimiter] | None = getattr(state, "_rate_limiters", None)
        if limiters is None:
            limiters = {}
            state._rate_limiters = limiters
        limiter = limiters.get(name)
        if limiter is None:
            settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, f"{name}_rate_limit"),
                window_seconds=getattr(settings, f"{name}_rate_window"),
            )
            limiters[name] = limiter
        limiter(request)

    dep.__name__ = f"rate_limit_{name}"
    dep.__doc__ = f"Per-IP rate limit for the '{name}' endpoint group."
    return dep

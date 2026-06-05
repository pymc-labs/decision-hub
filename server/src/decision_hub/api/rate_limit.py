"""In-memory sliding-window rate limiter for FastAPI dependencies."""

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

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

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
            # Check every 100 requests (cheap modulo on list length).
            total = sum(len(v) for v in self._requests.values())
            if total % 100 == 0:
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def make_rate_limit_dep(
    name: str,
    max_attr: str,
    window_attr: str,
) -> Callable[[Request], None]:
    """Build a FastAPI dependency that enforces a named per-IP rate limit.

    Replaces the ``_enforce_<name>_rate_limit`` boilerplate that used to
    be copy-pasted across every route module.  The returned callable
    lazily constructs a :class:`RateLimiter` on first use, caches it on
    ``request.app.state`` under ``f"_{name}_rate_limiter"`` (so it
    survives across requests within the same container), and then
    delegates to it.

    Args:
        name: Logical identifier (e.g. ``"publish"``, ``"search"``).
            Used both for the cache attribute and the function's
            ``__name__`` — keep it stable so debug/trace output is
            readable.
        max_attr: Attribute on ``settings`` that holds the request
            count (e.g. ``"publish_rate_limit"``).
        window_attr: Attribute on ``settings`` that holds the window
            length in seconds.

    Returns:
        A callable suitable for ``Depends(...)``.
    """
    state_attr = f"_{name}_rate_limiter"

    def dep(request: Request) -> None:
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

    dep.__name__ = f"enforce_{name}_rate_limit"
    dep.__qualname__ = dep.__name__
    dep.__doc__ = f"Rate-limit dependency for the {name!r} endpoint group."
    return dep

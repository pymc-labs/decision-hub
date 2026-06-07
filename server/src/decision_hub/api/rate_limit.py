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


def make_rate_limit_dependency(
    name: str,
    *,
    max_requests_setting: str,
    window_seconds_setting: str,
) -> Callable[[Request], None]:
    """Build a FastAPI dependency that lazily creates a per-app ``RateLimiter``.

    Previously each route declared its own ``_enforce_*_rate_limit`` wrapper
    -- nine near-identical copies across registry, search, and auth routes.
    This factory collapses that boilerplate. The limiter is cached on
    ``app.state`` under ``_<name>_rate_limiter`` so it is built once per
    container, and its limits are read from settings by attribute name so
    each route keeps its independent budget.

    Args:
        name: Used as the limiter's identifier and the attribute key on
            ``app.state``. Pick the same short label the route is named for
            (e.g. ``"publish"``, ``"download"``, ``"auth"``).
        max_requests_setting: Name of the Settings attribute holding the
            request budget (e.g. ``"publish_rate_limit"``).
        window_seconds_setting: Name of the Settings attribute holding the
            window length in seconds (e.g. ``"publish_rate_window"``).

    Returns:
        A callable suitable for use with ``Depends(...)``. Calling it with
        a ``Request`` records the hit and raises HTTP 429 when over budget.
    """
    state_attr = f"_{name}_rate_limiter"

    def _dependency(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, state_attr, None)
        if limiter is None:
            settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, max_requests_setting),
                window_seconds=getattr(settings, window_seconds_setting),
            )
            setattr(state, state_attr, limiter)
        limiter(request)

    # Give the closure a stable, debuggable name in stack traces and
    # OpenAPI dependency lists.
    _dependency.__name__ = f"enforce_{name}_rate_limit"
    _dependency.__qualname__ = _dependency.__name__
    return _dependency

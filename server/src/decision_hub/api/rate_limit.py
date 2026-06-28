"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict

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


def enforce_rate_limit(
    request: Request,
    *,
    name: str,
    max_requests: int,
    window_seconds: int,
) -> None:
    """Lazily build (once per container) and invoke a named rate limiter.

    The limiter is cached on ``request.app.state`` under
    ``_rate_limiter_<name>`` so that all routes sharing a name share a
    single sliding-window counter. Callers pre-read ``max_requests`` and
    ``window_seconds`` from ``Settings`` so this helper does not need to
    know about settings field names.

    Use this from a tiny per-route shim::

        def _enforce_publish_rate_limit(request: Request) -> None:
            s: Settings = request.app.state.settings
            enforce_rate_limit(
                request,
                name="publish",
                max_requests=s.publish_rate_limit,
                window_seconds=s.publish_rate_window,
            )
    """
    state = request.app.state
    attr = f"_rate_limiter_{name}"
    limiter = getattr(state, attr, None)
    if limiter is None:
        limiter = RateLimiter(max_requests=max_requests, window_seconds=window_seconds)
        setattr(state, attr, limiter)
    limiter(request)


def make_rate_limit_dep(
    name: str,
    limit_field: str,
    window_field: str,
):
    """Return a FastAPI dependency that enforces a named rate limit.

    ``limit_field`` and ``window_field`` are attribute names looked up on
    ``Settings`` at call time, so the dependency stays decoupled from the
    settings values (handy in tests that override the env)::

        _enforce_publish_rate_limit = make_rate_limit_dep(
            "publish", "publish_rate_limit", "publish_rate_window"
        )

    The returned callable is a plain function so FastAPI's ``Depends``
    treats it like any other dependency (sync, no request body parsing).
    """

    def _dep(request: Request) -> None:
        settings: Settings = request.app.state.settings
        enforce_rate_limit(
            request,
            name=name,
            max_requests=getattr(settings, limit_field),
            window_seconds=getattr(settings, window_field),
        )

    _dep.__name__ = f"_enforce_{name}_rate_limit"
    _dep.__doc__ = f"Rate-limit dependency for the '{name}' bucket."
    return _dep

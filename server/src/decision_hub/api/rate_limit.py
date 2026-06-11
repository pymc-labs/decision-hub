"""In-memory sliding-window rate limiter for FastAPI dependencies."""

from __future__ import annotations

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


# ---------------------------------------------------------------------------
# Dependency factory
# ---------------------------------------------------------------------------

# Per-endpoint rate limiters are eagerly registered on app.state during
# create_app() so that:
#   * the first request to each endpoint doesn't pay the init cost,
#   * there is no first-request race window on `hasattr` + assignment,
#   * the settings → limiter wiring is centralised (one source of truth).


def install_rate_limiters(app_state, settings) -> None:
    """Eagerly install all rate limiters on ``app.state``.

    Each *name* must correspond to a pair of settings fields:
    ``<name>_rate_limit`` and ``<name>_rate_window``. The limiter is
    stored on ``app_state._<name>_rate_limiter`` and looked up by
    ``rate_limit_dep`` below.
    """
    for name in _RATE_LIMIT_NAMES:
        max_requests = getattr(settings, f"{name}_rate_limit")
        window_seconds = getattr(settings, f"{name}_rate_window")
        setattr(
            app_state,
            f"_{name}_rate_limiter",
            RateLimiter(max_requests=max_requests, window_seconds=window_seconds),
        )


def rate_limit_dep(name: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency that enforces the limiter named *name*.

    The limiter must already exist on ``request.app.state`` (installed by
    :func:`install_rate_limiters`). If it's missing — e.g. in a test app
    that didn't call ``install_rate_limiters`` — we fall back to creating
    one from settings so existing tests continue to pass.
    """
    attr = f"_{name}_rate_limiter"

    def dep(request: Request) -> None:
        state = request.app.state
        limiter: RateLimiter | None = getattr(state, attr, None)
        if limiter is None:
            settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, f"{name}_rate_limit"),
                window_seconds=getattr(settings, f"{name}_rate_window"),
            )
            setattr(state, attr, limiter)
        limiter(request)

    dep.__name__ = f"rate_limit_{name}"
    dep.__doc__ = f"Enforce the '{name}' rate limit (settings.{name}_rate_limit per settings.{name}_rate_window s)."
    return dep


# Canonical list of rate-limiter names. The corresponding settings fields
# (``<name>_rate_limit`` and ``<name>_rate_window``) must exist on
# :class:`Settings`. Add new names here when introducing a new public
# endpoint that needs rate limiting.
_RATE_LIMIT_NAMES: tuple[str, ...] = (
    "auth",
    "search",
    "list_skills",
    "resolve",
    "similar_skills",
    "download",
    "audit_log",
    "scan_report",
    "publish",
)

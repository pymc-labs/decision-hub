"""In-memory sliding-window rate limiter and registry for FastAPI dependencies.

Limiters are created once at app startup and looked up by name on every
request. Each container holds its own state — limits are *per-container*,
not shared across Modal replicas. That's acceptable for the goal of
preventing a single client from hammering a single container.
"""

import threading
import time
from collections.abc import Callable
from typing import Protocol

from fastapi import HTTPException, Request

from decision_hub.settings import Settings


class _Clock(Protocol):
    def __call__(self) -> float: ...


class RateLimiter:
    """Per-IP sliding-window rate limiter.

    Tracks request timestamps per client IP in memory. Thread-safe:
    FastAPI runs sync dependencies in a threadpool so concurrent access
    is guarded by a lock.

    The clock is injected so tests can advance time deterministically
    (no ``time.sleep`` needed). Defaults to ``time.monotonic``.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        *,
        clock: _Clock = time.monotonic,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clock = clock
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = self._clock()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = [t for t in self._requests.get(key, ()) if t > cutoff]

            if len(timestamps) >= self.max_requests:
                # Re-store the pruned list so memory stays bounded even on rejection.
                self._requests[key] = timestamps
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests "
                        f"per {self.window_seconds}s). Try again shortly."
                    ),
                )

            timestamps.append(now)
            self._requests[key] = timestamps

            # Periodically purge stale IPs to bound memory growth.
            total = sum(len(v) for v in self._requests.values())
            if total % 100 == 0:
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold ``self._lock``."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


class RateLimiterRegistry:
    """Eagerly-constructed collection of named limiters.

    Created once at app startup (``create_app``) and stored on
    ``app.state.rate_limiters``. Eager construction eliminates a TOCTOU
    race that the previous lazy ``hasattr(state, ...)`` pattern had:
    two requests arriving simultaneously could both create new limiters
    and silently lose tracked timestamps.
    """

    def __init__(self) -> None:
        self._limiters: dict[str, RateLimiter] = {}

    def register(self, name: str, limiter: RateLimiter) -> None:
        if name in self._limiters:
            raise ValueError(f"Rate limiter {name!r} already registered")
        self._limiters[name] = limiter

    def get(self, name: str) -> RateLimiter:
        try:
            return self._limiters[name]
        except KeyError as exc:
            raise KeyError(f"Rate limiter {name!r} not registered. Known limiters: {sorted(self._limiters)}") from exc


# Mapping of public limiter name -> (max-requests setting, window setting).
# Single source of truth that ``build_rate_limiter_registry`` walks at
# startup.  Adding a new limiter is one line here plus the corresponding
# ``Depends(rate_limit("..."))`` on the route.
_LIMITER_SPEC: tuple[tuple[str, str, str], ...] = (
    ("search", "search_rate_limit", "search_rate_window"),
    ("auth", "auth_rate_limit", "auth_rate_window"),
    ("list_skills", "list_skills_rate_limit", "list_skills_rate_window"),
    ("resolve", "resolve_rate_limit", "resolve_rate_window"),
    ("similar_skills", "similar_skills_rate_limit", "similar_skills_rate_window"),
    ("download", "download_rate_limit", "download_rate_window"),
    ("audit_log", "audit_log_rate_limit", "audit_log_rate_window"),
    ("publish", "publish_rate_limit", "publish_rate_window"),
    ("scan_report", "scan_report_rate_limit", "scan_report_rate_window"),
)


def build_rate_limiter_registry(settings: Settings) -> RateLimiterRegistry:
    """Build all named limiters from settings. Call once at app startup."""
    registry = RateLimiterRegistry()
    for name, max_attr, window_attr in _LIMITER_SPEC:
        registry.register(
            name,
            RateLimiter(
                max_requests=getattr(settings, max_attr),
                window_seconds=getattr(settings, window_attr),
            ),
        )
    return registry


def rate_limit(name: str) -> Callable[[Request], None]:
    """Return a FastAPI dependency that enforces the named rate limiter.

    Usage::

        @router.get("/foo", dependencies=[Depends(rate_limit("search"))])
        def foo(...): ...
    """

    def _enforce(request: Request) -> None:
        registry: RateLimiterRegistry = request.app.state.rate_limiters
        registry.get(name)(request)

    return _enforce

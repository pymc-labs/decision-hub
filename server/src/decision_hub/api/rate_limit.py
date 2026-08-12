"""In-memory sliding-window rate limiter for FastAPI dependencies.

Each named limiter is built once at application startup from the matching
``<name>_rate_limit`` / ``<name>_rate_window`` fields on :class:`Settings`.
Route modules ask for the limiter by name via :func:`limiter_dep`, which
returns a FastAPI dependency callable — no per-route boilerplate, no
lazy ``hasattr`` initialisation on ``app.state`` (which raced when two
threads first hit an endpoint concurrently, silently discarding the loser's
counter).
"""

import threading
import time
from collections import defaultdict
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

    # Purge stale IP buckets every N requests. Amortises O(n_ips) work
    # across many cheap O(1) request checks so a bursty-IP attack cannot
    # inflate the per-request cost.
    _PURGE_EVERY = 100

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        # Monotonic counter of admitted requests -- used to trigger the
        # periodic purge. sum(len(v) for v in ...) previously ran per
        # request under the lock (O(n_ips)) and could easily never land
        # on exactly 100, so the purge fired at unpredictable intervals
        # or not at all.
        self._request_count = 0

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

            self._request_count += 1
            if self._request_count % self._PURGE_EVERY == 0:
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


class RateLimiters:
    """Container of eagerly-constructed named rate limiters.

    One instance is built in :func:`create_app` from :class:`Settings` and
    attached to ``app.state.rate_limiters``. Named limiters are looked up
    at import time by route modules via :func:`limiter_dep`.

    Attribute names follow the convention ``<name>_rate_limit`` /
    ``<name>_rate_window`` on :class:`Settings` (e.g. ``publish`` reads
    ``publish_rate_limit`` and ``publish_rate_window``). Adding a new
    limiter is one entry in ``_NAMES`` here plus the pair of settings
    fields.
    """

    _NAMES: tuple[str, ...] = (
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

    def __init__(self, settings: Settings) -> None:
        self._limiters: dict[str, RateLimiter] = {}
        for name in self._NAMES:
            self._limiters[name] = RateLimiter(
                max_requests=getattr(settings, f"{name}_rate_limit"),
                window_seconds=getattr(settings, f"{name}_rate_window"),
            )

    def get(self, name: str) -> RateLimiter:
        try:
            return self._limiters[name]
        except KeyError as exc:
            raise KeyError(f"Unknown rate limiter '{name}'. Known: {sorted(self._limiters)}") from exc


def limiter_dep(name: str) -> Callable[[Request], None]:
    """Return a FastAPI dependency that enforces the named rate limiter.

    Usage::

        @router.get("/foo", dependencies=[Depends(limiter_dep("resolve"))])
        def foo(...): ...

    Resolution happens per request via ``request.app.state.rate_limiters``
    so the returned callable is safe to bind at module import time — the
    settings-driven limiters do not need to exist yet.
    """

    def _dep(request: Request) -> None:
        limiters: RateLimiters = request.app.state.rate_limiters
        limiters.get(name)(request)

    _dep.__name__ = f"enforce_{name}_rate_limit"
    return _dep

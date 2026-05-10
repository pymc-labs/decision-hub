"""In-memory sliding-window rate limiter for FastAPI dependencies.

Routes opt into rate limiting via ``Depends(rate_limit("<name>"))``. The
``<name>`` indexes a per-app dictionary of pre-built ``RateLimiter``
instances (``app.state.rate_limiters``) populated by
``build_rate_limiters()`` during ``create_app()``. Eager construction
avoids a subtle race in the previous lazy-init pattern where two
concurrent first-requests could each create a fresh limiter and the
second would silently overwrite the first's accumulated state.
"""

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


# ---------------------------------------------------------------------------
# Declarative rate-limit registry
# ---------------------------------------------------------------------------
#
# Each route that needs rate limiting picks a name from this table. The same
# name is used in ``Depends(rate_limit("<name>"))`` and indexes into
# ``app.state.rate_limiters``. Adding a new rate-limited route is a 3-step
# change: (1) add ``<name>_rate_limit`` / ``<name>_rate_window`` to settings;
# (2) add a row here; (3) attach ``Depends(rate_limit("<name>"))`` to the
# route. No more copy-pasted lazy-init helpers.

_RATE_LIMIT_NAMES: tuple[str, ...] = (
    "search",
    "list_skills",
    "resolve",
    "similar_skills",
    "download",
    "audit_log",
    "publish",
    "auth",
    "scan_report",
)


def build_rate_limiters(settings: Settings) -> dict[str, RateLimiter]:
    """Build the per-app rate-limiter dictionary from settings.

    Called once during ``create_app()``; the resulting dict is stored on
    ``app.state.rate_limiters`` and shared across all worker threads of a
    container. Each name maps to a fresh ``RateLimiter`` sized by the
    ``<name>_rate_limit`` / ``<name>_rate_window`` pair on Settings.
    """
    return {
        name: RateLimiter(
            max_requests=getattr(settings, f"{name}_rate_limit"),
            window_seconds=getattr(settings, f"{name}_rate_window"),
        )
        for name in _RATE_LIMIT_NAMES
    }


def rate_limit(name: str):
    """Return a FastAPI dependency that applies the named rate limiter.

    The dependency reads ``app.state.rate_limiters[name]`` (built eagerly
    by ``create_app``). When the dictionary is missing — for example in
    test apps that bypass ``create_app`` — the dependency lazily builds
    it from ``app.state.settings`` so test fixtures don't have to
    duplicate the wiring.

    Raises:
        KeyError: At dependency-call time if ``name`` is not registered
            in ``_RATE_LIMIT_NAMES``. This is a programming error, not a
            runtime condition: it surfaces during the first request to
            the misnamed route, never silently degrades.
    """
    if name not in _RATE_LIMIT_NAMES:
        # Fail at import time so typos in route definitions never reach prod.
        raise KeyError(f"Unknown rate-limit name '{name}'. Register it in _RATE_LIMIT_NAMES.")

    def _dep(request: Request) -> None:
        state = request.app.state
        limiters = getattr(state, "rate_limiters", None)
        if limiters is None:
            # Fallback path for test apps that don't go through create_app().
            # Production always pre-builds the dict, so this branch is cold.
            limiters = build_rate_limiters(state.settings)
            state.rate_limiters = limiters
        limiters[name](request)

    _dep.__name__ = f"rate_limit_{name}"
    return _dep

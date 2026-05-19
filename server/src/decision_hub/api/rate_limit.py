"""In-memory sliding-window rate limiter for FastAPI dependencies.

Two shapes are exposed:

- ``RateLimiter`` — a callable dependency keyed on the client IP, used as
  ``dependencies=[Depends(limiter)]`` on a route.
- ``register_rate_limiters(app, settings)`` — builds every limiter the API
  needs at startup and parks them on ``app.state``, so route modules can pull
  them by name via ``get_rate_limiter(request, "<name>")``.

Lazy ``hasattr``-based initialisation inside each route's dependency was
racy: two concurrent requests on a fresh container could both pass the
``hasattr`` check and stomp each other's limiter, splitting the counter
across two independent buckets and leaking requests over the cap. Building
limiters up front removes that race and the eight near-identical
``_enforce_*`` helpers that previously lived in each routes module.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from decision_hub.settings import Settings


# Pruning cadence — every Nth call we walk the dict and drop IPs that have
# fallen out of the window. Chosen empirically: small enough that idle keys
# don't accumulate under sustained traffic, large enough that prune cost is
# amortised. Was previously gated on ``total % 100 == 0`` which fired
# unpredictably when the dict shrank, so we now count calls explicitly.
_PRUNE_INTERVAL = 200


class RateLimiter:
    """Per-key sliding-window rate limiter.

    Tracks request timestamps per client in memory. Works well for Modal
    serverless containers where each container handles its own traffic.
    Counters are not shared across containers — for typical abuse patterns
    (one client hammering one container) that's fine; document the global
    cap as ``per-container * replicas`` if you need a strict upper bound.

    Thread-safe: FastAPI runs sync dependencies in a threadpool, so a lock
    guards the shared state. The per-key timestamp store is a ``deque`` so
    that pruning expired entries is amortised O(1) per call rather than the
    O(n) list rebuild the previous implementation paid on every request.

    Usage as a FastAPI dependency::

        limiter = RateLimiter(max_requests=10, window_seconds=60)

        @router.get("/search", dependencies=[Depends(limiter)])
        def search(...): ...
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        *,
        trust_forwarded_for: bool = False,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.trust_forwarded_for = trust_forwarded_for
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._calls_since_prune = 0

    def _client_key(self, request: Request) -> str:
        """Return the rate-limit key for *request*.

        When ``trust_forwarded_for`` is set we honour the left-most
        ``X-Forwarded-For`` entry, which is the original client when the
        request comes through a single trusted hop (Modal's HTTPS edge in
        our deployment). Without this, ``request.client.host`` is the
        proxy's IP and every caller shares one bucket. Only enable when
        you actually run behind a proxy that sets the header; otherwise a
        client can spoof it to evade the limit.
        """
        if self.trust_forwarded_for:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                first = forwarded.split(",", 1)[0].strip()
                if first:
                    return first
        return request.client.host if request.client else "unknown"

    def __call__(self, request: Request) -> None:
        key = self._client_key(request)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._requests[key]
            # deque.popleft is amortised O(1); the previous list-comp
            # rebuilt the entire history on every request.
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests per "
                        f"{self.window_seconds}s). Try again shortly."
                    ),
                )

            timestamps.append(now)
            self._calls_since_prune += 1
            if self._calls_since_prune >= _PRUNE_INTERVAL:
                self._calls_since_prune = 0
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove keys with no recent activity. Caller must hold ``self._lock``."""
        stale = [k for k, ts in self._requests.items() if not ts or ts[-1] <= cutoff]
        for k in stale:
            del self._requests[k]


# ---------------------------------------------------------------------------
# Centralised registration so routes can look up named limiters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _LimiterSpec:
    name: str
    max_attr: str
    window_attr: str


# Single source of truth for which limiters exist and which settings drive
# them. Adding a new limiter is one line here plus a Depends() on the route.
_LIMITER_SPECS: tuple[_LimiterSpec, ...] = (
    _LimiterSpec("search", "search_rate_limit", "search_rate_window"),
    _LimiterSpec("list_skills", "list_skills_rate_limit", "list_skills_rate_window"),
    _LimiterSpec("resolve", "resolve_rate_limit", "resolve_rate_window"),
    _LimiterSpec("similar_skills", "similar_skills_rate_limit", "similar_skills_rate_window"),
    _LimiterSpec("download", "download_rate_limit", "download_rate_window"),
    _LimiterSpec("audit_log", "audit_log_rate_limit", "audit_log_rate_window"),
    _LimiterSpec("publish", "publish_rate_limit", "publish_rate_window"),
    _LimiterSpec("auth", "auth_rate_limit", "auth_rate_window"),
    _LimiterSpec("scan_report", "scan_report_rate_limit", "scan_report_rate_window"),
)


def register_rate_limiters(app, settings: Settings) -> None:
    """Build every limiter declared in ``_LIMITER_SPECS`` and attach to ``app.state``.

    Called once from ``create_app()``. Storing them on ``app.state.rate_limiters``
    lets route modules grab the one they need without each maintaining its
    own ``_enforce_*`` helper, and avoids the previous TOCTOU race in lazy
    init under concurrent first-request load.

    ``trust_forwarded_for`` is read from settings — enabling it without a
    trusted proxy would let any caller pick their own rate-limit bucket.
    """
    limiters: dict[str, RateLimiter] = {}
    for spec in _LIMITER_SPECS:
        limiters[spec.name] = RateLimiter(
            max_requests=getattr(settings, spec.max_attr),
            window_seconds=getattr(settings, spec.window_attr),
            trust_forwarded_for=settings.trust_forwarded_for,
        )
    app.state.rate_limiters = limiters


def get_rate_limiter(request: Request, name: str) -> RateLimiter:
    """Fetch the named limiter from ``app.state``.

    Raises ``KeyError`` at request time if the name is misspelled — caught in
    tests, never at runtime in production code paths that go through
    ``rate_limited()`` below.
    """
    return request.app.state.rate_limiters[name]


def rate_limited(name: str):
    """Return a FastAPI dependency that enforces the named limiter.

    Used like ``dependencies=[Depends(rate_limited("search"))]`` on a route.
    """

    def _dependency(request: Request) -> None:
        get_rate_limiter(request, name)(request)

    _dependency.__name__ = f"rate_limited_{name}"
    return _dependency

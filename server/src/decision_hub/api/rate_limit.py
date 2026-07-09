"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict

from fastapi import Depends, HTTPException, Request

from decision_hub.settings import Settings

# Purge stale IPs every this many calls to bound memory growth.
_PURGE_INTERVAL = 500


def _extract_client_ip(request: Request, *, trust_forwarded_for: bool) -> str:
    """Return the effective client IP for rate-limiting.

    In production the app runs behind a load balancer (Modal), so
    ``request.client.host`` is the LB's IP -- every user shares one
    key.  When ``trust_forwarded_for`` is True, the left-most token
    of the ``X-Forwarded-For`` header is used instead, giving each
    real caller its own bucket.  When False (e.g. local dev where the
    header is user-controllable), only the socket peer is trusted.
    """
    if trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # X-Forwarded-For may contain a comma-separated chain; the
            # left-most token is the original client, subsequent tokens
            # are intermediate proxies.
            first = forwarded.split(",", 1)[0].strip()
            if first:
                return first
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Per-IP sliding-window rate limiter.

    Tracks request timestamps per client IP in memory.  Works well for
    Modal serverless containers where each container handles its own
    traffic.  Not shared across containers -- that's fine for preventing
    a single client from hammering a single container.

    Thread-safe: FastAPI runs sync dependencies in a threadpool, so
    concurrent access to shared state is guarded by a lock.

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
        trust_forwarded_for: bool = True,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.trust_forwarded_for = trust_forwarded_for
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._call_count = 0

    def __call__(self, request: Request) -> None:
        key = _extract_client_ip(request, trust_forwarded_for=self.trust_forwarded_for)
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
            # Call-count based (not sum-of-lists) so cost is constant per call
            # instead of O(N) where N is the number of tracked IPs.
            self._call_count += 1
            if self._call_count % _PURGE_INTERVAL == 0:
                self._purge_stale(cutoff)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


# ---------------------------------------------------------------------------
# FastAPI dependency factory
# ---------------------------------------------------------------------------


def rate_limit(name: str):
    """Build a FastAPI dependency that enforces the ``{name}`` rate limit.

    Rate limits are keyed by ``name`` and lazily materialised on
    ``app.state`` on first use so tests can reset them per-app.
    Settings are read from ``settings.{name}_rate_limit`` and
    ``settings.{name}_rate_window``.

    Example::

        @router.get("/skills", dependencies=[Depends(rate_limit("list_skills"))])
        def list_skills(...): ...

    This replaces the per-endpoint ``_enforce_*_rate_limit`` helpers,
    each of which duplicated the same lazy-init pattern.
    """
    attr = f"_rate_limiter_{name}"
    max_attr = f"{name}_rate_limit"
    window_attr = f"{name}_rate_window"

    def dependency(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, attr, None)
        if limiter is None:
            settings: Settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, max_attr),
                window_seconds=getattr(settings, window_attr),
                trust_forwarded_for=getattr(settings, "trust_forwarded_for", True),
            )
            setattr(state, attr, limiter)
        limiter(request)

    return dependency


def limit(name: str):
    """Convenience wrapper -- ``limit("publish")`` == ``Depends(rate_limit("publish"))``.

    Meant to be used inline in route ``dependencies=[...]`` lists.
    """
    return Depends(rate_limit(name))

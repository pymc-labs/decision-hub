"""In-memory sliding-window rate limiter for FastAPI dependencies.

Limiters are per-container (each Modal replica keeps its own state), which
is fine for protecting a single container from a single noisy client.  The
factory helpers below remove the ~10-line boilerplate that every route
otherwise duplicates: one ``make_rate_limit_dependency("publish")`` call
wires up a limiter that reads ``settings.publish_rate_limit`` and
``settings.publish_rate_window`` and lazily attaches it to ``app.state``.

Client identification honours the leftmost ``X-Forwarded-For`` value when
present so that Modal's load balancer (which proxies every request and
therefore makes ``request.client.host`` resolve to the LB itself, not the
caller) does not collapse every client into a single global bucket.  See
``_client_key`` for the precise rules and the trusted-header trade-off.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import HTTPException, Request


def _client_key(request: Request) -> str:
    """Return a stable per-client identifier suitable for bucket keying.

    Modal terminates TLS at its load balancer and forwards requests over an
    internal hop, so ``request.client.host`` is the LB IP — useless for
    per-IP throttling.  When ``X-Forwarded-For`` is present we use the
    leftmost value (the original caller in a standard proxy chain).  If
    absent, we fall back to ``request.client.host`` so local/test setups
    still work.

    Spoofing trade-off: a client *could* forge ``X-Forwarded-For``.  The
    realistic alternative — one shared bucket for the entire fleet — is
    strictly worse, and per-container limiters already bound the damage
    from a forged header to a single container.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class RateLimiter:
    """Per-client sliding-window rate limiter.

    Tracks request timestamps per client identifier in memory.  Works well
    for Modal serverless containers where each container handles its own
    traffic; state is not shared across replicas.  Thread-safe — FastAPI
    runs sync dependencies in a threadpool, so concurrent access is
    guarded by a lock.

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
        key = _client_key(request)
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
                        f"Rate limit exceeded ({self.max_requests} requests per "
                        f"{self.window_seconds}s). Try again shortly."
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


def make_rate_limit_dependency(name: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency that throttles by ``settings.<name>_rate_*``.

    Each unique ``name`` gets its own lazily-initialised :class:`RateLimiter`
    attached to ``app.state``, so the limiter is shared across all routes
    that call the same dependency in this container.

    Replaces nine near-identical ``_enforce_*_rate_limit`` helpers that
    each re-implemented this exact pattern.

    Args:
        name: Prefix for the matching ``settings.<name>_rate_limit`` and
            ``settings.<name>_rate_window`` fields.

    Returns:
        A dependency callable suitable for ``Depends(...)``.
    """
    state_attr = f"_{name}_rate_limiter"
    limit_attr = f"{name}_rate_limit"
    window_attr = f"{name}_rate_window"

    def enforce(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, state_attr, None)
        if limiter is None:
            settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, limit_attr),
                window_seconds=getattr(settings, window_attr),
            )
            setattr(state, state_attr, limiter)
        limiter(request)

    enforce.__name__ = f"enforce_{name}_rate_limit"
    enforce.__qualname__ = enforce.__name__
    return enforce

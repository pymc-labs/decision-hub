"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request

# Attribute name on `app.state` for the container-wide "trust the first hop of
# X-Forwarded-For" toggle. Set once at settings load — see `_client_key`.
_TRUST_PROXY_ATTR = "_rate_limit_trust_proxy"


def _client_key(request: Request) -> str:
    """Return the per-client key used to bucket rate-limit counters.

    Behind Modal / any TLS-terminating proxy, ``request.client.host`` is the
    proxy IP, so every request would share a single bucket — one attacker
    could exhaust the limit for the whole world. When ``rate_limit_trust_proxy``
    is set on ``app.state`` we honour the left-most entry of
    ``X-Forwarded-For``, which is the closest thing to a real client IP the
    proxy exposes. The setting is off by default so misconfigured deployments
    fail closed (spoofable header ignored) rather than open.
    """
    app = request.app
    if getattr(app.state, _TRUST_PROXY_ATTR, False):
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            first = xff.split(",", 1)[0].strip()
            if first:
                return first
    return request.client.host if request.client else "unknown"


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


def rate_limit_dependency(name: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency that lazily initialises a per-endpoint limiter.

    The returned callable expects the app to carry a ``settings`` attribute on
    ``app.state`` with ``<name>_rate_limit`` and ``<name>_rate_window`` fields.
    The limiter is created on first use and cached at ``app.state._<name>_rate_limiter``
    so all requests to that endpoint share the same sliding window.

    This replaces ~9 near-identical `_enforce_*_rate_limit` helpers that only
    differed by the settings field they read.
    """
    state_attr = f"_{name}_rate_limiter"
    limit_attr = f"{name}_rate_limit"
    window_attr = f"{name}_rate_window"

    def _enforce(request: Request) -> None:
        state = request.app.state
        limiter: Any = getattr(state, state_attr, None)
        if limiter is None:
            settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, limit_attr),
                window_seconds=getattr(settings, window_attr),
            )
            setattr(state, state_attr, limiter)
        limiter(request)

    _enforce.__name__ = f"_enforce_{name}_rate_limit"
    _enforce.__doc__ = f"Rate-limit dependency for the '{name}' endpoint group."
    return _enforce

"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request

from decision_hub.api.client_ip import client_ip


def _resolve_trusted_proxy_count(request: Request) -> int:
    """Read ``trusted_proxy_count`` from app settings, defaulting to 0.

    Defends against unit tests that pass a bare ``MagicMock`` request: those
    have a Mock chain on ``request.app.state.settings`` whose attributes are
    Mocks rather than ints, so we coerce non-int values to 0.
    """
    settings = getattr(getattr(request.app, "state", None), "settings", None)
    value = getattr(settings, "trusted_proxy_count", 0)
    return value if isinstance(value, int) else 0


class RateLimiter:
    """Per-IP sliding-window rate limiter.

    Tracks request timestamps per client IP in memory. Works well for
    Modal serverless containers where each container handles its own
    traffic. Not shared across containers -- that's fine for preventing
    a single client from hammering a single container.

    Thread-safe: FastAPI runs sync dependencies in a threadpool, so
    concurrent access to shared state is guarded by a lock.

    Behind a reverse proxy (Modal, Cloudflare, ALB, ...) the request's
    direct ``client.host`` is the proxy's IP, identical for every real
    client.  The settings field ``trusted_proxy_count`` controls how many
    hops to skip in ``X-Forwarded-For``; when zero the limiter falls back
    to ``request.client.host`` for direct deployments.

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
        key = client_ip(request, trusted_proxy_count=_resolve_trusted_proxy_count(request))
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

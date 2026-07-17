"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request

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


def _client_key(request: Request) -> str:
    """Return the rate-limit key for a request.

    Prefers the leftmost entry in ``X-Forwarded-For`` (the original
    client's IP as recorded by the edge proxy) so that Modal / other
    reverse-proxied deployments don't collapse every request into one
    bucket keyed on the proxy address. Falls back to
    ``request.client.host`` when no header is present.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


# Serialize lazy limiter creation so two concurrent cold-start requests
# don't each construct their own limiter and undercount the first burst.
_LIMITER_INIT_LOCK = threading.Lock()


def make_rate_limit_dependency(
    attr_name: str,
    max_requests_setting: str,
    window_seconds_setting: str,
) -> Callable[[Request], None]:
    """Return a FastAPI dependency that lazily builds a per-app rate limiter.

    Previously every route wired up its own copy-pasted 8-line
    ``_enforce_*_rate_limit`` function that read settings, stored the
    limiter on ``app.state``, and called it. That was racy under
    concurrent cold-start requests (two threads could both see
    ``hasattr = False`` and create competing limiters, losing counts) and
    added ~100 lines of duplicated boilerplate across route modules.

    Args:
        attr_name: attribute name on ``request.app.state`` where the
            limiter is cached (e.g. ``"_search_rate_limiter"``).
        max_requests_setting: name of the ``Settings`` field holding the
            request cap (e.g. ``"search_rate_limit"``).
        window_seconds_setting: name of the ``Settings`` field holding
            the window size in seconds.
    """

    def dependency(request: Request) -> None:
        state = request.app.state
        limiter = getattr(state, attr_name, None)
        if limiter is None:
            with _LIMITER_INIT_LOCK:
                # Re-check inside the lock: another thread may have
                # created it while we were waiting.
                limiter = getattr(state, attr_name, None)
                if limiter is None:
                    settings: Settings = state.settings
                    limiter = RateLimiter(
                        max_requests=getattr(settings, max_requests_setting),
                        window_seconds=getattr(settings, window_seconds_setting),
                    )
                    setattr(state, attr_name, limiter)
        limiter(request)

    return dependency


def rate_limit(
    attr_name: str,
    max_requests_setting: str,
    window_seconds_setting: str,
) -> Depends:
    """Shorthand for ``Depends(make_rate_limit_dependency(...))``."""
    return Depends(make_rate_limit_dependency(attr_name, max_requests_setting, window_seconds_setting))

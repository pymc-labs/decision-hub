"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request

# Purge stale IP buckets on a fixed cadence rather than after a running total
# that (a) requires an O(N) sum on every hit and (b) is arithmetically brittle
# when the population isn't a multiple of the modulus.
_PURGE_EVERY_HITS = 100


def _client_ip(request: Request) -> str:
    """Return the caller's public IP, honouring the reverse proxy in front of the app.

    Modal (and any typical load balancer) terminates TCP at the edge, so
    ``request.client.host`` is always the same LB address — all real users
    would share one bucket, and one noisy client would 429 everyone else.
    ``X-Forwarded-For`` is the standard chain; the *leftmost* entry is the
    client that connected to the outermost proxy. ``X-Real-IP`` is a common
    fallback set by some deployments. We trust these headers because Modal
    strips inbound copies before invoking the app; when running locally
    without a proxy neither header is set and we fall back to the transport
    peer.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # Leftmost address in the chain is the originating client.
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        real_ip = real_ip.strip()
        if real_ip:
            return real_ip
    if request.client is not None:
        return request.client.host
    return "unknown"


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
        # Counter (not a modulo over a live sum) so purge fires deterministically.
        self._hits_since_purge = 0

    def __call__(self, request: Request) -> None:
        key = _client_ip(request)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            # Prune expired timestamps for this key.
            timestamps = self._requests[key]
            self._requests[key] = [t for t in timestamps if t > cutoff]

            if len(self._requests[key]) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests per {self.window_seconds}s). "
                        "Try again shortly."
                    ),
                )

            self._requests[key].append(now)

            self._hits_since_purge += 1
            if self._hits_since_purge >= _PURGE_EVERY_HITS:
                self._purge_stale(cutoff)
                self._hits_since_purge = 0

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def make_rate_limit_dependency(
    name: str,
    limit_attr: str,
    window_attr: str,
) -> Callable[..., None]:
    """Build a FastAPI dependency that lazily instantiates a shared limiter.

    Every rate-limited route in the app followed the identical shape:

        def _enforce_x_rate_limit(request):
            state = request.app.state
            if not hasattr(state, "_x_rate_limiter"):
                state._x_rate_limiter = RateLimiter(
                    max_requests=state.settings.x_rate_limit,
                    window_seconds=state.settings.x_rate_window,
                )
            state._x_rate_limiter(request)

    This factory replaces those hand-rolled copies with one call. The
    limiter is stashed on ``app.state`` under ``_{name}_rate_limiter`` so it
    stays a per-container singleton and picks up its bounds from the
    settings attributes named by ``limit_attr`` / ``window_attr``.

    Args:
        name: Short slug used as the ``app.state`` attribute suffix.
        limit_attr: Name of the ``Settings`` attribute holding the max requests.
        window_attr: Name of the ``Settings`` attribute holding the window seconds.
    """
    state_attr = f"_{name}_rate_limiter"

    def dependency(request: Request) -> None:
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

    dependency.__name__ = f"_enforce_{name}_rate_limit"
    dependency.__doc__ = f"Rate-limit dependency for {name!r} using settings.{limit_attr}/{window_attr}."
    return dependency


def rate_limit(
    name: str,
    limit_attr: str,
    window_attr: str,
) -> Depends:
    """Return ``Depends(make_rate_limit_dependency(...))`` — a router-level shortcut."""
    return Depends(make_rate_limit_dependency(name, limit_attr, window_attr))

"""In-memory sliding-window rate limiter for FastAPI dependencies.

The Decision Hub server runs behind Modal's TLS-terminating ingress, which
means ``request.client.host`` is the proxy address — every request would
look like the same client and per-IP limits would collapse to a global
container limit.  We therefore consult ``X-Forwarded-For`` (set by Modal)
and use its leftmost entry as the originating client.  Falling back to
``request.client.host`` keeps the limiter useful in tests and in any
deployment that doesn't set the header.

The limiter also uses a bounded ``deque`` per IP and an LRU-style cap on
the number of tracked IPs so that a flood of distinct addresses can't
grow the per-container memory unboundedly.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque

from fastapi import HTTPException, Request

from decision_hub.settings import Settings

# Cap on the number of distinct client IPs tracked simultaneously per
# container.  Beyond this we evict the least-recently-used IP — which can
# only happen for an IP whose window is, by definition, in the past or
# has already been blocked.  Sized to comfortably fit any realistic
# legitimate-user fan-out while putting a hard ceiling on attack memory.
_MAX_TRACKED_IPS = 10_000


def client_ip(request: Request) -> str:
    """Return the originating client IP for rate-limiting and logging.

    Honours the leftmost address in ``X-Forwarded-For`` (set by Modal's
    ingress proxy and by most reverse proxies).  Falls back to the
    direct socket peer when the header is missing or malformed.

    The leftmost-untrusted approach is appropriate here because the
    Modal frontend overwrites the header on every request — a client
    cannot spoof its own IP unless the Modal ingress forwards a
    spoofable header verbatim, which it does not.
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
    """Per-IP sliding-window rate limiter.

    Tracks request timestamps per client IP in memory.  Works well for
    Modal serverless containers where each container handles its own
    traffic.  Not shared across containers — that's intentional, since
    the goal is preventing a single client from hammering a single
    container, not enforcing a global cap.

    Memory bounds: at most :data:`_MAX_TRACKED_IPS` IPs are kept; each
    IP holds at most ``max_requests`` timestamps in a ``deque`` (with
    expired entries popped on every call).  An OrderedDict provides
    LRU eviction so old IPs naturally fall out as new ones appear.

    Thread-safe: FastAPI runs sync dependencies in a threadpool, so all
    mutation is guarded by a single lock.
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def __call__(self, request: Request) -> None:
        key = client_ip(request)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._requests.get(key)
            if timestamps is None:
                timestamps = deque()
                self._requests[key] = timestamps
            else:
                # Refresh LRU position so this IP is the most recent.
                self._requests.move_to_end(key)

            # Drop expired timestamps from the left of the window.
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests "
                        f"per {self.window_seconds}s). Try again shortly."
                    ),
                )

            timestamps.append(now)

            # LRU cap.  Evict the oldest IP until we're under the limit.
            # The oldest entry is by definition the least recently active,
            # so its window has either already expired or it is rate-limited
            # and therefore won't notice the eviction.
            while len(self._requests) > _MAX_TRACKED_IPS:
                self._requests.popitem(last=False)


def make_rate_limit_dep(
    name: str,
    *,
    limit_attr: str,
    window_attr: str,
):
    """Build a FastAPI dependency that lazily wires a per-route ``RateLimiter``.

    The dependency caches a single :class:`RateLimiter` instance on
    ``app.state`` keyed by *name*, so repeated calls reuse it across
    requests within the same container.  Limit and window come from
    :class:`Settings` so behaviour stays configurable per environment.

    Args:
        name: Unique identifier — used as the ``app.state`` attribute.
        limit_attr: Name of the ``Settings`` attribute holding ``max_requests``.
        window_attr: Name of the ``Settings`` attribute holding ``window_seconds``.

    Returns:
        A FastAPI dependency callable suitable for ``Depends(...)``.
    """
    state_key = f"_rate_limiter_{name}"

    def dependency(request: Request) -> None:
        state = request.app.state
        limiter: RateLimiter | None = getattr(state, state_key, None)
        if limiter is None:
            settings: Settings = state.settings
            limiter = RateLimiter(
                max_requests=getattr(settings, limit_attr),
                window_seconds=getattr(settings, window_attr),
            )
            setattr(state, state_key, limiter)
        limiter(request)

    dependency.__name__ = f"rate_limit_{name}"
    dependency.__doc__ = f"Rate-limit dependency for the '{name}' endpoint group."
    return dependency

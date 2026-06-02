"""In-memory sliding-window rate limiter for FastAPI dependencies.

Two public surfaces:

* ``RateLimiter`` -- the limiter itself.  Per-IP sliding window stored
  in memory; not shared across Modal containers (each container limits
  its own traffic).

* ``make_rate_limit_dep(name)`` -- factory that returns a FastAPI
  dependency wired to the per-endpoint settings ``<name>_rate_limit`` /
  ``<name>_rate_window``.  Eliminates the per-route copy/paste of an
  ``_enforce_<name>_rate_limit`` function and centralises the lazy-init
  behaviour (which previously had a small ``hasattr`` race when two
  requests arrived before the first one finished installing the limiter
  on ``app.state``).

The module also exposes ``client_ip_from_request`` which honours the
first hop in ``X-Forwarded-For`` so per-IP buckets behave correctly
when the app sits behind a load balancer (Modal, CloudFront, etc.).
Without it, ``request.client.host`` is the proxy IP and every real
client shares one bucket.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import HTTPException, Request

# Purge stale per-IP buckets every N calls.  Previously the limiter
# tried to purge "every 100 requests" by checking ``total % 100 == 0``
# against the sum of all stored timestamps -- a value that can skip the
# zero modulo entirely as old entries expire, leaving stale IPs in
# memory indefinitely.  A monotonic per-instance counter is both
# simpler and reliable.
_PURGE_EVERY_N_CALLS = 256


def client_ip_from_request(request: Request) -> str:
    """Return the originating client IP for rate-limiting / log context.

    Falls back through:
    1. The first hop in ``X-Forwarded-For`` (when the app sits behind a
       trusted proxy like Modal's edge or CloudFront).
    2. ``request.client.host`` (direct connection / local dev).
    3. The string ``"unknown"`` -- shared bucket, but never crashes.

    We intentionally do not validate the IP format here; an attacker
    spoofing the header just isolates themselves into their own bucket
    which is the worst case anyway.  Production deployments that need
    strict trust should terminate untrusted ``X-Forwarded-For`` at the
    proxy layer.
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
        self._calls_since_purge = 0

    def __call__(self, request: Request) -> None:
        key = client_ip_from_request(request)
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

            # Periodic purge based on the number of calls handled --
            # deterministic regardless of how many IPs are active.
            self._calls_since_purge += 1
            if self._calls_since_purge >= _PURGE_EVERY_N_CALLS:
                self._purge_stale(cutoff)
                self._calls_since_purge = 0

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]


def make_rate_limit_dep(name: str) -> Callable[[Request], None]:
    """Build a FastAPI dependency that enforces a per-endpoint rate limit.

    ``name`` must match the prefix of a pair of settings fields:
    ``<name>_rate_limit`` and ``<name>_rate_window``.  The limiter
    instance is cached on ``app.state`` under ``_<name>_rate_limiter``
    so a fresh container builds it once on first use and every
    subsequent request reuses it.

    Lazy init is guarded by a process-wide lock to avoid the
    benign-but-noisy race where two early requests each built their
    own limiter and the second overwrote the first (resetting the
    sliding window for any IP already tracked).

    Usage::

        list_skills_rate_limit = make_rate_limit_dep("list_skills")

        @router.get("/skills", dependencies=[Depends(list_skills_rate_limit)])
        def list_skills(...): ...
    """
    state_attr = f"_{name}_rate_limiter"

    def dep(request: Request) -> None:
        state = request.app.state
        limiter: RateLimiter | None = getattr(state, state_attr, None)
        if limiter is None:
            with _init_lock:
                # Re-check inside the lock: another thread may have
                # installed the limiter while we were waiting.
                limiter = getattr(state, state_attr, None)
                if limiter is None:
                    settings = state.settings
                    limiter = RateLimiter(
                        max_requests=getattr(settings, f"{name}_rate_limit"),
                        window_seconds=getattr(settings, f"{name}_rate_window"),
                    )
                    setattr(state, state_attr, limiter)
        limiter(request)

    dep.__name__ = f"_enforce_{name}_rate_limit"
    return dep


# Single module-level lock shared by every dependency returned from
# ``make_rate_limit_dep``.  Contention is negligible (only hit on the
# very first request per limiter per container).
_init_lock = threading.Lock()

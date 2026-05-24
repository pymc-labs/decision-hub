"""In-memory sliding-window rate limiter for FastAPI dependencies.

The limiter keys on the **client IP**, which behind a proxy (Modal, Cloudflare,
ALB) is *not* ``request.client.host`` — that field reports the *immediate*
peer, i.e. the proxy itself. Without honouring ``X-Forwarded-For`` every
request collapses onto a single key and the limiter degrades into a global
counter that throttles all traffic together.

The forwarded-IP parsing is configurable so self-hosters who do not run
behind a trusted proxy can opt out and avoid IP spoofing via the header.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

# Hard cap on distinct IPs we'll remember at once. Cheap insurance against
# memory growth from a slow header-spray attack.  Once exceeded the limiter
# proactively evicts the IP with the oldest most-recent request.
_MAX_TRACKED_KEYS = 100_000

# How many *accepted* requests pass through before we attempt a stale-IP
# sweep.  Using a counter (not ``len(dict) % N``) is deterministic and avoids
# the trap of the previous implementation, which triggered the sweep when
# ``total`` happened to be 0 — i.e. on every single request to an empty
# limiter.
_SWEEP_EVERY_N_REQUESTS = 256


def _client_key(request: Request, trust_forwarded_for: bool) -> str:
    """Resolve the per-client rate-limit key.

    When ``trust_forwarded_for`` is True, prefer the left-most entry of
    ``X-Forwarded-For`` (the originating client per RFC 7239 convention).
    Otherwise fall back to the immediate peer address.

    Returns ``"unknown"`` if no address is available — collapses anonymous
    test/CI traffic onto one bucket, which is the safer default than
    leaving such requests unlimited.
    """
    if trust_forwarded_for:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # Left-most non-empty entry, stripped of whitespace and any
            # ``[ipv6]:port`` style port suffix.
            first = xff.split(",", 1)[0].strip()
            if first:
                return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class RateLimiter:
    """Per-IP sliding-window rate limiter.

    Tracks request timestamps per client IP in memory.  Per-container only;
    when traffic fans out across Modal replicas each replica enforces its
    own quota.  That is intentional — the goal is to keep one abusive
    client from saturating a single container, not to enforce a global
    quota.

    The timestamp store is a :class:`collections.deque` so pruning expired
    entries from the head is O(k) instead of the previous O(n) list
    comprehension that allocated a fresh list every call.

    Thread-safe: FastAPI runs sync dependencies in a threadpool.

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
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        # Total requests seen since last sweep — drives periodic eviction
        # without scanning the dict on every call.
        self._since_sweep = 0

    def __call__(self, request: Request) -> None:
        key = _client_key(request, self.trust_forwarded_for)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._requests[key]

            # Drop expired entries from the head — O(k) per call where k is
            # the number of entries that just fell out of the window, not
            # the size of the deque.
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
            self._since_sweep += 1

            # Amortised cleanup of stale IPs.  Doing it on every accepted
            # request would dominate the request path; doing it never lets
            # the dict grow unboundedly under a slow IP-rotation attack.
            if self._since_sweep >= _SWEEP_EVERY_N_REQUESTS:
                self._since_sweep = 0
                self._purge_stale(cutoff)
            elif len(self._requests) > _MAX_TRACKED_KEYS:
                # Hard cap — evict the IP whose most-recent request is
                # oldest.  Bounded O(N) but only triggered in the
                # pathological case.
                self._evict_oldest()

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no entries inside the window. Caller holds the lock."""
        stale = [k for k, ts in self._requests.items() if not ts or ts[-1] <= cutoff]
        for k in stale:
            del self._requests[k]

    def _evict_oldest(self) -> None:
        """Evict the single oldest-tail IP. Caller holds the lock.

        Used only when ``_MAX_TRACKED_KEYS`` is exceeded — chooses the
        least-recently-active key so genuinely active clients keep their
        history.
        """
        if not self._requests:
            return
        oldest_key = min(
            self._requests,
            key=lambda k: self._requests[k][-1] if self._requests[k] else 0.0,
        )
        del self._requests[oldest_key]


def get_or_create_limiter(
    request: Request,
    name: str,
    max_requests: int,
    window_seconds: int,
) -> RateLimiter:
    """Return a per-app ``RateLimiter`` instance, creating it on first use.

    Limiters live on ``app.state`` under ``_rate_limiter_<name>`` so each
    endpoint can share one limiter across requests without route-level
    globals.  The lazy-init pattern was previously copy-pasted into eight
    near-identical ``_enforce_*_rate_limit`` helpers; this collapses them
    into a single source of truth.

    Concurrency note: ``app.state`` writes during init are racy if two
    requests arrive before any limiter has been created.  Worst case we
    construct two limiter objects and one is dropped — harmless because
    no traffic has been recorded against the dropped one yet.
    """
    attr = f"_rate_limiter_{name}"
    limiter = getattr(request.app.state, attr, None)
    if limiter is None:
        limiter = RateLimiter(
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
        setattr(request.app.state, attr, limiter)
    return limiter

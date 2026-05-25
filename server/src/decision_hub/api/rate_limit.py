"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request

# Hard cap on the number of distinct keys we track. Bounds worst-case
# memory under adversarial input (rotating fake client IPs in a forged
# header). When exceeded we drop the oldest-touched keys.
_MAX_TRACKED_KEYS = 50_000

# Minimum interval between full prunes. Per-key pruning still happens on
# every call so correctness doesn't depend on this — it only governs how
# often we sweep empty keys out of the dict.
_FULL_PRUNE_INTERVAL_SECONDS = 60.0


def client_ip(request: Request, *, trust_proxy_headers: bool = False) -> str:
    """Return the request's client IP for rate-limit bucketing.

    When ``trust_proxy_headers`` is True, prefer the *first* address in
    ``X-Forwarded-For`` (the original client), then ``X-Real-IP``, then
    the socket peer. This is required behind reverse proxies (Modal,
    Cloud Run, nginx, ELB) where ``request.client.host`` is the proxy
    address — collapsing every public client into a single bucket and
    rendering the per-IP limiter useless.

    When ``trust_proxy_headers`` is False (the default for safety), we
    use the socket peer and ignore proxy headers — otherwise a client
    can spoof its own header to forge a bucket key.

    Returns ``"unknown"`` when no client information is available.
    """
    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # The header is a comma-separated chain; the original client
            # is the leftmost entry. Each hop appends, so trailing
            # entries are nearer the server.
            first = forwarded.split(",", 1)[0].strip()
            if first:
                return first
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
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

    When the application is deployed behind a reverse proxy, construct
    with ``trust_proxy_headers=True`` so the limiter buckets on the
    real client IP rather than the proxy's.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        *,
        trust_proxy_headers: bool = False,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.trust_proxy_headers = trust_proxy_headers
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._last_full_prune: float = 0.0

    def __call__(self, request: Request) -> None:
        key = client_ip(request, trust_proxy_headers=self.trust_proxy_headers)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            # Per-key prune: only the bucket we're touching, so this is
            # O(window_size) not O(num_keys).
            timestamps = [t for t in self._requests[key] if t > cutoff]

            if len(timestamps) >= self.max_requests:
                # Write back the pruned list so memory doesn't grow
                # unbounded for hammered keys.
                self._requests[key] = timestamps
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded ({self.max_requests} requests per {self.window_seconds}s). Try again shortly."
                    ),
                )

            timestamps.append(now)
            self._requests[key] = timestamps

            # Periodic full sweep — bounded by wall time, not by the
            # (broken) "if total % 100 == 0" trick the old code used.
            # Summing list lengths every request was O(num_keys); the
            # check fired constantly under low traffic (everyone at 1
            # touches "% 100 == 0" of 1) and rarely under spikes.
            if now - self._last_full_prune > _FULL_PRUNE_INTERVAL_SECONDS:
                self._purge_stale(cutoff)
                self._last_full_prune = now

            # Hard cap on dictionary size. Without this, an adversary
            # who can set the bucket key (real client IP, or spoofed
            # X-Forwarded-For if we ever trust it without a private
            # peer) could exhaust container memory.
            if len(self._requests) > _MAX_TRACKED_KEYS:
                self._evict_to_cap(cap=_MAX_TRACKED_KEYS)

    def _purge_stale(self, cutoff: float) -> None:
        """Remove IPs with no recent activity. Caller must hold self._lock."""
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]

    def _evict_to_cap(self, *, cap: int) -> None:
        """Drop oldest-touched keys until the dict has ``cap`` entries.

        Sorts by most-recent-timestamp; keys with empty lists rank as
        oldest. Caller must hold ``self._lock``.
        """
        items = sorted(
            self._requests.items(),
            key=lambda kv: kv[1][-1] if kv[1] else 0.0,
        )
        excess = len(self._requests) - cap
        for k, _ in items[:excess]:
            del self._requests[k]

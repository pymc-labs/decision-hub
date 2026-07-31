"""In-memory sliding-window rate limiter for FastAPI dependencies."""

import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable

from fastapi import HTTPException, Request

# Sentinel used when the true client IP cannot be identified.  Kept identical
# to the historical value so any operator dashboards that alert on it continue
# to work.
_UNKNOWN_CLIENT = "unknown"


def _extract_client_ip(request: Request, trusted_proxies: Iterable[str] = ()) -> str:
    """Return the caller's IP, honouring ``X-Forwarded-For`` behind trusted proxies.

    When Modal (or any reverse proxy) terminates the TCP connection, every
    request's ``request.client.host`` is the proxy IP — so a per-IP rate
    limiter keyed on it collapses all users into one bucket and lets a
    single client throttle the platform.  Reading ``X-Forwarded-For`` is
    only safe when the direct peer is a trusted proxy, otherwise a client
    could just send the header themselves and spoof any origin.

    Args:
        request: The FastAPI request.
        trusted_proxies: Iterable of peer IPs (or prefixes matched with
            ``str.startswith``) that we accept ``X-Forwarded-For`` from.
            Empty (the default) preserves the pre-refactor behaviour of
            keying on ``request.client.host`` only.

    Returns:
        A string suitable for use as a rate-limit bucket key.
    """
    peer_ip = request.client.host if request.client else ""
    trusted = tuple(trusted_proxies)

    # Only trust the header when the direct socket peer is a known proxy.
    # Fall back to the peer IP for direct connections and unknown origins.
    if trusted and peer_ip and any(peer_ip == p or peer_ip.startswith(p) for p in trusted):
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            # X-Forwarded-For is a comma-separated chain "client, proxy1, proxy2".
            # The leftmost non-empty entry is the original client.
            for candidate in forwarded.split(","):
                ip = candidate.strip()
                if ip:
                    return ip

    return peer_ip or _UNKNOWN_CLIENT


class RateLimiter:
    """Per-client sliding-window rate limiter.

    Tracks request timestamps per client key in memory.  Works well for
    Modal serverless containers where each container handles its own
    traffic.  Not shared across containers -- that's fine for preventing
    a single client from hammering a single container.

    Thread-safe: FastAPI runs sync dependencies in a threadpool, so
    concurrent access to shared state is guarded by a lock.

    When ``trusted_proxies`` is configured the limiter keys off the
    original client IP from ``X-Forwarded-For`` instead of the proxy's
    socket IP — required for any deployment behind a reverse proxy /
    edge terminator (Modal, Cloudflare, etc.).  See ``_extract_client_ip``.

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
        trusted_proxies: Iterable[str] = (),
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._trusted_proxies: tuple[str, ...] = tuple(trusted_proxies)
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def __call__(self, request: Request) -> None:
        key = _extract_client_ip(request, self._trusted_proxies)
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


# ---------------------------------------------------------------------------
# Dependency factory
# ---------------------------------------------------------------------------


def rate_limited(
    name: str,
    *,
    limit_attr: str,
    window_attr: str,
) -> Callable[[Request], None]:
    """Return a FastAPI dependency that lazily attaches a per-endpoint limiter.

    Every route file used to inline a 12-line ``_enforce_*_rate_limit`` helper
    that (1) looked up the limiter on ``request.app.state``, (2) instantiated
    it on first use from settings, and (3) invoked it.  This factory collapses
    all nine copies into one small closure.

    The limiter is stored on ``app.state`` under a private attribute derived
    from ``name`` (e.g. ``_publish_rate_limiter``) so it survives across
    requests within a container and is reachable for tests / introspection.

    Args:
        name: A short slug (e.g. ``"publish"``); used for the ``app.state``
            attribute name.  Must be unique per endpoint.
        limit_attr: Name of the ``Settings`` field with the max-requests
            value (e.g. ``"publish_rate_limit"``).
        window_attr: Name of the ``Settings`` field with the window-seconds
            value (e.g. ``"publish_rate_window"``).

    Returns:
        A callable suitable for ``Depends(...)``.  Raises ``HTTPException(429)``
        when the caller exceeds the configured budget.
    """
    state_attr = f"_{name}_rate_limiter"

    def _dependency(request: Request) -> None:
        state = request.app.state
        limiter: RateLimiter | None = getattr(state, state_attr, None)
        if limiter is None:
            settings = state.settings
            trusted = getattr(settings, "trusted_proxies", "") or ""
            proxies = tuple(p.strip() for p in trusted.split(",") if p.strip())
            limiter = RateLimiter(
                max_requests=getattr(settings, limit_attr),
                window_seconds=getattr(settings, window_attr),
                trusted_proxies=proxies,
            )
            setattr(state, state_attr, limiter)
        limiter(request)

    _dependency.__name__ = f"_enforce_{name}_rate_limit"
    return _dependency

"""Resolve the originating client IP behind a chain of trusted proxies.

Modal (and most cloud edges) terminate TLS at a proxy and forward the
request to the application container.  In that setup, ``request.client.host``
is the proxy's internal IP — identical for every real client — which makes
per-IP rate limiting and per-IP logging useless.  The originating client IP
is appended to ``X-Forwarded-For`` by the trusted proxy.

``X-Forwarded-For`` has a left-to-right order:

    X-Forwarded-For: <client>, <proxy1>, <proxy2>

Reading the leftmost value naively trusts the client (which may have set the
header itself), so we instead skip ``trusted_proxy_count`` entries from the
right.  The setting is exposed via ``Settings.trusted_proxy_count`` and
defaults to ``0`` — i.e. read ``request.client.host`` and ignore the header
entirely, preserving the historical behaviour for environments without a
trusted proxy.
"""

from __future__ import annotations

from fastapi import Request

_FORWARDED_FOR_HEADER = "x-forwarded-for"


def client_ip(request: Request, trusted_proxy_count: int = 0) -> str:
    """Return the best-effort originating client IP for *request*.

    Args:
        request: The FastAPI/Starlette request.
        trusted_proxy_count: Number of trusted proxies between this app and
            the client.  ``0`` (default) ignores ``X-Forwarded-For`` and
            returns ``request.client.host`` — the safe default for direct
            deployments.  ``1`` strips one entry from the right (correct for
            Modal and most single-proxy deployments).  Higher values are
            useful when the request crosses multiple in-house proxies.

    Returns:
        The resolved client IP, or the string ``"unknown"`` when no
        identifying information is available.
    """
    if trusted_proxy_count > 0:
        forwarded = request.headers.get(_FORWARDED_FOR_HEADER)
        if forwarded:
            # Each comma-separated entry may have surrounding whitespace.
            ips = [part.strip() for part in forwarded.split(",") if part.strip()]
            if ips:
                # Walk from the right past the trusted proxies.  If the chain
                # is shorter than declared, fall through to the leftmost
                # entry (the originating client per the standard).
                idx = max(0, len(ips) - trusted_proxy_count - 1)
                return ips[idx]

    if request.client is not None:
        return request.client.host

    return "unknown"
